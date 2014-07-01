deployment-formula
==================

Simplified deployment using salt. Heavily inspired by capistrano.
In one state function you combine:
- clone git repo
- build application (i.e. bundle install or virtualenv && ./bin/pip install)
- test application (optional)
- if failed that execute specified command (optional)
- link to application/current
- link log directory
- restart service (optional)

Where each following step will only be triggered by success of a previous one.

By default state ensures that only 5 latest deployments are kept on server.

PS: There is whole bunch of rollback roll forward module functions to have way more granular control.
See module docstrings for more help.


On rev
------
If you pass branch than by default it will follow the branch. So every state.highstate will trigger check if upgrade is available.
This can be disabled with: `update_branch: False`.

If you pass tag or version hash than it will stick to this version.


example states usage
--------------------

Let's create application user::

    your_appslug:
      user:
        - present
        - home: /srv/your_appslug
        - shell: /bin/bash


...than it's time to get create directory structure::

    your_appslug-skeleton:
      deployment.skeleton:
        - name: /srv/your_appslug/application
        - user: your_appslug
        - group: your_appslug


...and finally let's ensure that app is deployed::

    deploy-pvb:
      deployment.ensure:
        - name: /srv/your_appslug/application
        - repository: git@github.com:abc/def.git
        - rev: master
        - update_branch: True
        - user: pvb
        - deploy_cmd: |
            bundle install --deployment --without test
            bundle exec rake assets:precompile
            bundle exec rake APP_PLATFORM=production RAILS_ENV=production RAILS_GROUPS=assets static_pages:generate


notes
-----
It's nice to combine deployment.ensure with `watch_in: service restart` so that deployment will trigger application
restart. Other way to start the service is to pass service restart command as parameter to deployment.ensure.
See `activate_cmd` parameter.
