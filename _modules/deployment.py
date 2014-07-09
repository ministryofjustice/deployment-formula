import os
import yaml
import logging

from datetime import datetime

from salt.exceptions import CommandExecutionError
from salt.utils.odict import OrderedDict

log = logging.getLogger(__name__)

#__salt__ = {}
#__opts__ = {}

def skeleton(name,
         user=None,
         group=None,
         mode=None,
         makedirs=False):
    """
    sets up directory structure for application
    TODO: consider making /var/log/slug structure as well (against: too MOJ specific)
    TODO: consider linking to /var/log (against: too MOJ specific)
    """
    # Remove trailing slash, if present
    if name[-1] == '/':
        name = name[:-1]

    changes = {}

    dirs_to_make = [
        name,
        name + '/releases',
        name + '/shared',
        name + '/shared/log',
        name + '/shared/pids',
        name + '/shared/system',
        name + '/shared/tmp',
        name + '/shared/session',
    ]

    if makedirs and os.path.isdir(os.path.dirname(name)):
        __salt__['file.makedirs'](
            name, user=user, group=group, mode=mode
        )
        changes[name] = 'New Dir'

    for directory in dirs_to_make:
        if not os.path.isdir(directory):
            # The dir does not exist, make it
            if not __opts__['test']:
                __salt__['file.mkdir'](directory, user=user, group=group, mode=mode)
            changes[directory] = 'New Dir'

    return changes


def generate_tag():
    """
    generates release tag based on current time
    """
    now = datetime.now()
    return now.strftime("%Y%m%d%H%M%S")


def deploy(name,
           repository,
           rev=None,
           user=None,  # falls back to releases directory owner
           group=None,  # falls back to releases directory group
           deploy_cmd=None,  # executed on deploy
           test_cmd=None,  # executed to verify deploy (before linking)
           on_failed_cmd=None,  # executed on failed deploy
           activate_cmd=None,  # i.e. to tell supervisor to restart the app
           tag=None,  # overwrite to generate deployment tags yourself (i.e. to orchestrate from overstate)
           ):
    """
    deploys specific repo, and commit

    tests app
    if all ok than it updates current link

    creates tag/META file
    and returns it enhanced with tag: tag and current:True

    """
    meta = {
        'commit': None,
        'rev': rev,
        'scm': 'git',
        'deploy_cmd': None,
        'test_cmd': None,
        'ok': False,
    }

    def on_failed():
        if on_failed_cmd:
            log.info("executing on_failed_cmd")
            res = __salt__['cmd.run_all'](
                on_failed_cmd, cwd=directory, runas=user
            )
            if res['retcode'] != 0:
                raise CommandExecutionError('Error executing on_failed_cmd: {0}'.format(on_failed_cmd))

    def save_meta():
        with open(os.path.join(directory, 'META'), mode='w') as f:
            f.write(yaml.dump(meta, default_flow_style=False))

    if not tag:
        tag = generate_tag()
    directory = os.path.join(name, 'releases', tag)

    directory_stats = os.stat(os.path.join(name, 'releases'))
    if not user:
        user = __salt__['file.uid_to_user'](directory_stats.st_uid)

    if not group:
        group = __salt__['file.gid_to_group'](directory_stats.st_gid)

    uid = __salt__['file.user_to_uid'](user)
    gid = __salt__['file.group_to_gid'](group)

    __salt__['git.clone'](directory, repository=repository, user=user)
    log.info("repository cloned successfully")

    if rev:
        __salt__['git.checkout'](directory, rev, force=True, user=user)
        log.info("version {0} checkout successful".format(rev))

    commit = __salt__['git.revision'](directory, user=user)
    meta['commit'] = commit
    log.info("commit {0}".format(commit))

    if deploy_cmd:
        log.info("executing deploy_cmd")
        res = __salt__['cmd.run_all'](
            deploy_cmd, cwd=directory, runas=user
        )
        log.info("post deployment command")
        if res['retcode'] != 0:
            on_failed()
            meta['deploy_cmd'] = False
            save_meta()
            raise CommandExecutionError('Error executing deploy_cmd: {0}'.format(deploy_cmd))
        else:
            meta['deploy_cmd'] = True

    if test_cmd:
        log.info("executing test_cmd")
        res = __salt__['cmd.run_all'](
            test_cmd, cwd=directory, runas=user
        )
        if res['retcode'] != 0:
            on_failed()
            meta['test_cmd'] = False
            save_meta()
            raise CommandExecutionError('Error executing test_cmd: {0}'.format(test_cmd))
        else:
            meta['test_cmd'] = True

    logs_dir = os.path.join(name, 'shared', 'log')

    #rename logs within repo if it already exists
    deployment_log = os.path.join(directory, 'log')
    if os.path.exists(deployment_log):
        os.rename(deployment_log, "{0}-old".format(deployment_log))

    #link application/{tag}/log to -> application/shared/log
    symlink(logs_dir, deployment_log, uid=uid, gid=gid)

    meta['ok'] = True
    save_meta()

    select(name, tag=tag)
    meta['tag'] = tag
    meta['current'] = True

    if activate_cmd:
        activate(name, user=user, activate_cmd=activate_cmd)

    return meta


def rollback(name):
    """
    rolls back to previous working release
    Working release means there is a META file with ok:True
    """

    current_deployment_tag = current(name)['tag']

    tags_dict = available(name)
    if current_deployment_tag not in tags_dict.keys():
        raise CommandExecutionError('Current build {0} is not on the list releases. Please use deployment.select')

    previous_passed_deployment_tag = None
    for tag in tags_dict.keys():
        if tag == current_deployment_tag:
            break
        if tags_dict[tag].get('ok'):
            previous_passed_deployment_tag = tag

    if not previous_passed_deployment_tag:
        raise CommandExecutionError('Unable to find previous deployment. Please use deployment.select')

    log.info('Rolling back to {0}'.format(previous_passed_deployment_tag))
    return select(name, previous_passed_deployment_tag)


def rollforward(name):
    """
    rolls forward to previous working release
    Working release means there is a META file with ok:True
    """
    current_deployment_tag = current(name)['tag']

    tags_dict = available(name)
    if current_deployment_tag not in tags_dict.keys():
        raise CommandExecutionError('Current build {0} is not on the list releases. Please use deployment.select')

    next_passed_deployment_tag = None
    for tag in sorted(tags_dict.keys(), reverse=True):
        if tag == current_deployment_tag:
            break
        if tags_dict[tag].get('ok'):
            next_passed_deployment_tag = tag

    if not next_passed_deployment_tag:
        raise CommandExecutionError('Unable to find previous deployment. Please use deployment.select')

    log.info('Rolling back to {0}'.format(next_passed_deployment_tag))
    return select(name, next_passed_deployment_tag)


def current(name):
    """
    returns meta file for current deployment
    in case of no current deployment it will return empty dictionary
    """
    current_link_path = os.path.join(name, 'current')

    if not os.path.isdir(name):
        raise CommandExecutionError('Selected application directory {0} does not exist'.format(name))

    if not os.path.islink(current_link_path):
        return {}

    #TODO: assert that current links to proper directory
    current_deployment_tag = os.path.basename(os.readlink(current_link_path))

    return get_meta(name, current_deployment_tag)


def get_meta(name, tag):
    """
    returns meta data for specific tag
    it's gonna always update meta by adding to extra fields:
    - tag
    - path
    """
    try:
        with open(os.path.join(name, 'releases', tag, 'META')) as f:
            ret = yaml.load(f)
    except IOError:
        ret = {}

    ret['tag'] = tag
    ret['path'] = os.path.join(name, 'releases', tag)
    return ret


def available(name):
    """
    returns (OrderedDict) all installed releases in sorted order
    with information if they succeeded (taken from META file)
    """
    tags = OrderedDict()
    releases_directory = os.path.join(name, 'releases')

    if not os.path.isdir(name):
        raise CommandExecutionError('Selected application directory {0} does not exist'.format(name))

    if not os.path.isdir(releases_directory):
        raise CommandExecutionError('Selected application releases directory {0} does not exist'.format(name))

    for tag in sorted(os.listdir(releases_directory)):
        tags[tag] = get_meta(name, tag)
    return tags


def status(name):
    """
    returns ordered list (OrderedDict) of all available releases marking which one is currently selected
    """
    av = available(name)
    try:
        current_tag = current(name)['tag']
        av[current_tag]['current'] = True
    except CommandExecutionError:
        pass
    except KeyError:
        pass
    return av


def limit_history(name, keep=5):
    """
    removes all unused revisions except for number you want to keep (default 5)
    """
    av = status(name)
    tags_to_kill = av.keys()[:-keep]
    removed = []
    for tag in tags_to_kill:
        release = av[tag]
        if release.get('current', False):
           pass  # keep me
        else:
            __salt__['file.remove'](release['path'])
            removed.append(release)
            log.info('Removed old and unused deployment: {0}'.format(tag))

    return removed


def select(name, tag):
    """
    links specific release tag to current
    uses the same user as release tag directory
    assumes you know what you do (not META verification)
    """
    tag = str(tag)
    deployment_directory = os.path.join(name, 'releases', tag)
    current_link_path = os.path.join(name, 'current')

    if not os.path.isdir(deployment_directory):
        raise CommandExecutionError('Selected deployment tag {0} does not exist'.format(tag))

    directory_stats = os.stat(deployment_directory)

    if os.path.lexists(current_link_path):
        if not os.path.islink(current_link_path):
            raise CommandExecutionError('Path {0} exists and is not a link'.format(current_link_path))
        os.unlink(current_link_path)
    symlink(deployment_directory, current_link_path, directory_stats.st_uid, directory_stats.st_gid)

    log.info('Selected deployment {0}'.format(tag))
    return current(name)


def symlink(src, path, uid, gid):
    os.symlink(src, path)
    os.lchown(path, uid, gid)


def activate(name,
             user,
             activate_cmd,  # i.e. to tell supervisor to restart the app
             ):
    """
    It's recommended to notify the supervisor state instead of this command
    """
    log.info("executing activate_cmd")
    res = __salt__['cmd.run_all'](
        activate_cmd, cwd=name, runas=user
    )
    if res['retcode'] != 0:
        raise CommandExecutionError('Error executing activate_cmd: {0}'.format(activate_cmd))


def _user_from_path(path):
    path_stats = os.stat(path)
    return __salt__['file.uid_to_user'](path_stats.st_uid)


def git_is_detached(cwd, user=None):

    if not user:
        user = _user_from_path(cwd)

    cmd_is_detached = 'git symbolic-ref -q HEAD'
    is_detached = __salt__['cmd.run_all'](cmd_is_detached, cwd, runas=user)['retcode'] == 1

    return is_detached


def git_is_remote_ahead(cwd, branch, user=None):

    if not user:
        user = _user_from_path(cwd)

    __salt__['git.fetch'](cwd, user=user)
    diff_cmd = 'git diff {0} origin/{0}'.format(branch)
    diff_res = __salt__['cmd.run_all'](diff_cmd, cwd=cwd, output_loglevel='debug')
    if diff_res['stdout']:
        return True
    else:
        return False


#TODO: manage a local mirror (bare git repo) and than deploy from it
#at the moment it would require separate state
