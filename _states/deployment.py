import os
import copy
import json
import shlex
import logging
import yaml

import salt.utils
from salt.exceptions import CommandExecutionError
from salt._compat import string_types


log = logging.getLogger(__name__)


def _error(ret, err_msg):
    ret['result'] = False
    ret['comment'] = err_msg
    return ret


def skeleton(name,
         user=None,
         group=None,
         mode=None,
         makedirs=False):
    """
    /srv/yourapp/application:
        - deployment.skeleton

    creates stucture like this:
        name + '/releases',
        name + '/shared',
        name + '/shared/log',
        name + '/shared/pids',
        name + '/shared/system',
        name + '/shared/tmp',
        name + '/shared/session',

    so that you can manage current running deployment as a link:
        name + '/current'
    """

    ret = {
        'name': name,
        'changes': {},
        'result': True,
        'comment': ''
    }

    ret['changes'] = __salt__['deployment.skeleton'](name, user, group, mode, makedirs)

    return ret


#TODO: add watch_in to trigger supervisor restart
#TODO: __opts__['test']
def ensure(name,
           repository,
           rev=None,
           user=None,
           update_branch=True,  # if on branch than checks remote if branch has been updated and than redeploys
           deploy_cmd=None,  # executed on deploy
           test_cmd=None,  # executed to verify deploy (before linking)
           on_failed_cmd=None,  # executed on failed deploy
           activate_cmd=None,  # i.e. to tell supervisor to restart the app
           ):
    """
    Ensures that the specific revision of application is up and running on the server.

    Supported scm=git

    In case you've already deployed the commit/tag it skips it.
    In case you've already deployed the branch it first checks for updates and than upgrades only when necessary.
    """

    def update_me():
        if __opts__['test']:
            ret['result'] = None
            ret['comment'] = 'Calling deployment.deploy'
            return
        new_current = __salt__['deployment.deploy'](name, repository=repository, rev=rev, user=user, deploy_cmd=deploy_cmd, test_cmd=test_cmd, on_failed_cmd=on_failed_cmd, activate_cmd=activate_cmd)
        ret['changes']['new_current'] = new_current

    ret = {
        'name': name,
        'changes': {},
        'result': True,
        'comment': ''
    }

    current_meta = __salt__['deployment.current'](name)

    if 'rev' not in current_meta:
        log.info("Deploying app as there is no currently running")
        update_me()
        return ret

    if current_meta['rev'] == rev:
        if update_branch:
            is_on_branch = not __salt__['deployment.git_is_detached'](current_meta['path'])
            if is_on_branch and __salt__['deployment.git_is_remote_ahead'](current_meta['path'], current_meta['rev']):
                log.info("Deploying app as there is a new version on the branch on remote repository")
                update_me()
                return ret
    else:
        update_me()
        return ret

    return ret
