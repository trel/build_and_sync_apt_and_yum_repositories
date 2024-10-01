#!/usr/bin/env python
from __future__ import print_function

#=======================================================
# TODO
# - write log of packages added since -n
#=======================================================

import distutils.dir_util
import errno
import logging
import optparse
import os
import platform
import subprocess
import shutil
import sys
import time

script_path = os.path.dirname(os.path.realpath(__file__))

# behind load balancer
servers = {
    'packages': { 'ip': '152.54.5.114', 'gpg_key_id': 'ACF9B42B' }, # public IP, using certbot
    'unstable': { 'ip': '152.54.5.113', 'gpg_key_id': '9086C490' }, # public IP, using certbot
    'core-dev': { 'ip': '152.54.5.112', 'gpg_key_id': '055D7E48' }  # public IP, using certbot
}

operating_systems = {
    # up to 4.3.1
    'Centos_6':        'centos6',
    'Centos linux_7':  'centos7',
    'Almalinux 8':     'almalinux8',
    'RockyLinux_9':    'rockylinux9',
    'Opensuse _13':    'opensuse13.2',
    'Ubuntu_12':       'ubuntu12',
    'Ubuntu_14':       'ubuntu14',
    'Ubuntu_16':       'ubuntu16',
    'Ubuntu_18':       'ubuntu18',
    'Ubuntu_20':       'ubuntu20',
    'Ubuntu_22':       'ubuntu22',
    'Debian_11':       'debian11',
    'Debian_12':       'debian12',

    # 4.3.2 and later
    'deb11':           'debian11',
    'deb12':           'debian12',
    'el7':             'centos7',
    'el8':             'almalinux8',
    'el9':             'rockylinux9',
    'ub20.04':         'ubuntu20',
    'ub20':            'ubuntu20',
    'ub22.04':         'ubuntu22',
    'ub22':            'ubuntu22',
    'ub24.04':         'ubuntu24',
    'ub24':            'ubuntu24'

    }

def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else: raise

def run_cmd(cmd, run_env=False, unsafe_shell=False, check_rc=False):
    log = logging.getLogger(__name__)
    # run it
    if run_env == False:
        run_env = os.environ.copy()
    log.debug('run_env: {0}'.format(run_env))
    log.info('running: {0}, unsafe_shell={1}, check_rc={2}'.format(cmd, unsafe_shell, check_rc))
    if unsafe_shell == True:
        p = subprocess.Popen(cmd, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    else:
        p = subprocess.Popen(cmd, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    log.info('  stdout: {0}'.format(out.strip()))
    log.info('  stderr: {0}'.format(err.strip()))
    log.info('')
    if check_rc != False:
        if p.returncode != 0:
            log.error(check_rc)
            sys.exit(p.returncode)
    return p.returncode

def move_earlier_destination_aside(destination):
    log = logging.getLogger(__name__)
    if os.path.isdir(destination):
        collision_location = '{0}-old-{1}'.format(destination, time.strftime("%Y%m%d%H%M%s"))
        log.debug('copy collision detected - moving to [{0}]'.format(collision_location))
        os.rename(destination, collision_location)

def copy_from_jenkins_directory(jenkins_directory, staging_directory):
    log = logging.getLogger(__name__)
    log.info('copying recursively from [{0}]'.format(jenkins_directory))
    log.debug('copy source      [{0}]'.format(jenkins_directory))
    log.debug('copy destination [{0}]'.format(staging_directory))
    distutils.dir_util.copy_tree(jenkins_directory, staging_directory)

def rename_to_repository_convention(fullpath):
    log = logging.getLogger(__name__)
    for o in operating_systems:
        src = os.path.join(fullpath, o)
        if os.path.isdir(src):
            log.debug('rename source      [{0}]'.format(src))
            dst = os.path.join(fullpath, operating_systems[o])
            log.debug('rename destination [{0}]'.format(dst))
            # recursively merge src and dst
            distutils.dir_util.copy_tree(src, dst)
            shutil.rmtree(src)
        else:
            log.debug('rename source not found [{0}]'.format(src))

def sign_all_rpms_at_once(target_server, fullpath):
    log = logging.getLogger(__name__)
    cmd = 'rpmsign --addsign --key-id={0} --digest-algo=sha384 `find {1} -name "*.rpm" -size +0c`'.format(servers[target_server]['gpg_key_id'],fullpath)
    run_cmd(cmd, unsafe_shell=True, check_rc=True)

def add_packages_to_repository(staging_directory, target_server, target_repository_directory, repository_type, osversion, codename):
    log = logging.getLogger(__name__)
    source_directory = os.path.join(script_path, staging_directory, osversion)
    log.debug('source directory [{0}]'.format(source_directory))
    if os.path.isdir(source_directory):
        log.debug('source directory, exists')
        # remove all zero length, log, and output files
        for dirpath, dirs, files in os.walk(source_directory):
            for file in files:
                path = os.path.join(dirpath, file)
                log.debug('checking file [{0}]'.format(path))
                if os.stat(path).st_size == 0:
                    log.debug('zero, deleting')
                    os.remove(path)
                if path.endswith('.log'):
                    log.debug('log file, deleting')
                    os.remove(path)
                if path.endswith('.output'):
                    log.debug('output file, deleting')
                    os.remove(path)
        # produce repository files only if there are new files to process
        file_list = os.listdir(source_directory)
        log.debug('file list [{0}]'.format(file_list))
        file_count = len(os.listdir(source_directory))
        log.debug('file count [{0}]'.format(file_count))
        if file_count > 0:
            log.debug('source directory has files')
            working_dir = os.path.join(target_repository_directory, repository_type)
            mkdir_p(working_dir)
            os.chdir(working_dir)
            log.debug('working dir [{0}]'.format(working_dir))
            # APT
            if repository_type in ['apt']:
                # generate ORIGIN string
                origin_string = 'irods'
                if target_server in ['unstable', 'core-dev']:
                    origin_string = 'irods {0}'.format(target_server)
                # generate freight configuration file
                pwd = os.path.realpath(script_path)
                freight_configuration_file = os.path.join(pwd,'freight.conf')
                with open(freight_configuration_file,'w') as fh:
                    fh.write('VARLIB={0}\n'.format(os.path.join(pwd,'freight_library_{0}'.format(target_server))))
                    fh.write('VARCACHE={0}\n'.format(working_dir))
                    fh.write('GPG={0}\n'.format(servers[target_server]['gpg_key_id']))
                    fh.write('ORIGIN="{0}"\n'.format(origin_string))
                    fh.write('LABEL=\n')
                # freight-add (puts files into the freight_library)
                for dirpath, dirs, files in os.walk(source_directory):
                    for file in files:
                        if file.endswith('.deb'):
                            # copy file
                            path = os.path.join(dirpath, file)
                            cmd = ['freight', 'add', '-v', '-c', freight_configuration_file, path, 'apt/{0}'.format(codename)]
                            run_cmd(cmd, check_rc=True)
                            # remove file
                            os.remove(path)
                # freight-cache (creates and signs repo metadata)
                cmd = ['freight', 'cache', '-v', '-c', freight_configuration_file, 'apt/{0}'.format(codename)]
                run_cmd(cmd, check_rc=True)
            # YUM
            elif repository_type in ['yum']:
                repo_dir = '{0}/pool/{1}/x86_64'.format(working_dir, codename)
                # move files
                mkdir_p(repo_dir)
                for dirpath, dirs, files in os.walk(source_directory):
                    for file in files:
                        src = os.path.join(dirpath, file)
                        dst = os.path.join(repo_dir, file)
                        shutil.move(src, dst)
                # create repo metadata
                cmd = ['createrepo', '--database', repo_dir]
                run_cmd(cmd, check_rc=True)
                # sign repository metadata
                repo_file = '{0}/repodata/repomd.xml'.format(repo_dir)
                signed_repo_file = '{0}.asc'.format(repo_file)
                if os.path.isfile(signed_repo_file):
                    os.remove(signed_repo_file)
                cmd = ['gpg', '--detach-sign', '-u', servers[target_server]['gpg_key_id'], '--armor', repo_file]
                run_cmd(cmd, check_rc=True)
            else:
                log.error('unknown repository_type [{0}]'.format(repository_type))
        else:
            log.debug('no files found in [{0}]'.format(source_directory))

def force_symlink(file1, file2):
    try:
        os.symlink(file1, file2)
    except OSError, e:
        if e.errno == errno.EEXIST:
            os.remove(file2)
            os.symlink(file1, file2)

def build_centos7_releasever_symlinks(target_directory):
    # centos7 $releasever has three flavors that must be available
    yum_pool_dir = "{0}/yum/pool".format(target_directory)
    mkdir_p(yum_pool_dir)
    os.chdir(yum_pool_dir)
    for suffix in ['Client','Server','Workstation']:
        force_symlink('centos7','centos7{0}'.format(suffix))

def rsync_to_website(target_server, source_directory):
    log = logging.getLogger(__name__)
    # sync to packages.irods.org
    log.info('source_directory [{0}]'.format(source_directory))
    connection_string = 'tgr@{0}:/var/www/html/'.format(servers[target_server]['ip'])
    cmd = ['rsync', '-vrlpoD', source_directory+'/', connection_string+'/']
    log.info('syncing with {0}'.format(cmd))
    run_cmd(cmd)

def main():
    # check parameters
    usage = 'Usage: %prog [options] target_server'
    parser = optparse.OptionParser(usage)
    parser.add_option('-n', '--new', action='store_const', const=1, dest='new_directories', help='create new staging, target, freight directories, save existing')
    parser.add_option('-q', '--quiet', action='store_const', const=0, dest='verbosity', help='print less information to stdout')
    parser.add_option('-j', '--jenkins', action='store', type='string', dest='jenkins_directory', help='fullpath of jenkins job directory')
    parser.add_option('-v', '--verbose', action='count', dest='verbosity', default=1, help='print more information to stdout')
    (options, args) = parser.parse_args()
    if len(args) != 1:
        parser.error('incorrect number of arguments')
    if len(args) == 0:
        parser.print_usage()
        return 1
    if args[0] not in servers:
        parser.error('target_server value [{0}] not in [\'{1}\']'.format(args[0], '\', \''.join(s for s in servers)))
        return 1

    # configure logging
    log = logging.getLogger()
    if options.verbosity >= 2:
        log.setLevel(logging.DEBUG)
    elif options.verbosity == 1:
        log.setLevel(logging.INFO)
    else:
        log.setLevel(logging.WARNING)
    ch = logging.StreamHandler()
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    log.addHandler(ch)

    # do it
    target_server = args[0]
    log.debug('target server [{0}]'.format(target_server))
    staging_directory = os.path.join(script_path, '{0}-sources'.format(target_server))
    target_directory = os.path.join(script_path, '{0}-html'.format(target_server))
    freight_directory = os.path.join(script_path, 'freight_library_{0}'.format(target_server))
    if options.new_directories:
        log.debug("creating new staging_directory, saving earlier version")
        move_earlier_destination_aside(staging_directory)
        mkdir_p(staging_directory)
        log.debug("creating new target_directory, saving earlier version")
        move_earlier_destination_aside(target_directory)
        mkdir_p(target_directory)
        log.debug("creating new freight_directory, saving earlier version")
        move_earlier_destination_aside(freight_directory)
        mkdir_p(freight_directory)
    if options.jenkins_directory:
        log.debug("preparing to copy jenkins directory")
        copy_from_jenkins_directory(options.jenkins_directory, staging_directory)
        rename_to_repository_convention(staging_directory)
        sign_all_rpms_at_once(target_server, staging_directory)
# --- begin comment block when adding singular packages
    add_packages_to_repository(staging_directory, target_server, target_directory, 'yum', 'centos6', 'centos6')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'yum', 'centos7', 'centos7')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'yum', 'almalinux8', 'el8') # dnf, but still use yum as repository_type
    add_packages_to_repository(staging_directory, target_server, target_directory, 'yum', 'rockylinux9', 'el9') # dnf, but still use yum as repository_type
    add_packages_to_repository(staging_directory, target_server, target_directory, 'yum', 'opensuse13.2', 'opensuse13.2')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'apt', 'ubuntu12', 'precise')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'apt', 'ubuntu14', 'trusty')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'apt', 'ubuntu16', 'xenial')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'apt', 'ubuntu18', 'bionic')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'apt', 'ubuntu20', 'focal')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'apt', 'ubuntu22', 'jammy')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'apt', 'ubuntu24', 'noble')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'apt', 'debian11', 'bullseye')
    add_packages_to_repository(staging_directory, target_server, target_directory, 'apt', 'debian12', 'bookworm')
# --- end comment block when adding singular packages
    build_centos7_releasever_symlinks(target_directory)
#    rsync_to_website(target_server, target_directory)

if __name__ == '__main__':
    sys.exit(main())
