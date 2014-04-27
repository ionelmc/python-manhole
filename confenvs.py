from itertools import product, chain
from jinja2 import FileSystemLoader
from jinja2 import Environment
jinja = Environment(loader=FileSystemLoader('.'), trim_blocks=True, lstrip_blocks=True)

pythons = ['2.7', '2.6', '3.2', '3.3', '3.4', 'pypy']
deps = ['python-signalfd', 'python-signalfd gevent', 'python-signalfd eventlet', 'eventlet', 'gevent', '']
covers = [True, False]
envs = ['PATCH_THREAD=x', '']
skips = list(chain(
    # disable py3/pypy with eventlet/gevent
    product(['3.2', '3.3', '3.4', 'pypy'], [dep for dep in deps if 'eventlet' in dep or 'gevent' in dep], covers, envs),
))
tox = {}
for python, dep, cover, env in product(pythons, deps, covers, envs):
    if (python, dep, cover, env) not in skips:
        tox['-'.join(filter(None, (
            python,
            '-'.join(dep.replace('python-', '').split()),
            '' if cover else 'nocover',
            env and env.lower().replace('_', '').rstrip('=x'),
        )))] = {
            'python': 'python' + python if 'py' not in python else python,
            'deps': dep.split(),
            'cover': cover,
            'env': env,
        }

open('tox.ini', 'w').write(jinja.get_template('tox.tmpl.ini').render(envs=tox))
open('.travis.yml', 'w').write(jinja.get_template('.travis.tmpl.yml').render(envs=tox))
