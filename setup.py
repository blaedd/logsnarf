from setuptools import setup
import os
import sys
sys.path.insert(0, os.path.abspath('./src'))

from logsnarf import __version__

setup(
    name='logsnarf',
    version=__version__,
    packages=['logsnarf', 'logsnarf.docs'],
    package_dir={'': 'src'},
    url='http://github.com/blaedd/logsnarf',
    license='MIT',
    author='David MacKinnon',
    author_email='blaedd@gmail.com',
    description='Tool to stream log files to BigQuery',
  # setup_requires=['Sphinx', 'mock'],
    install_requires=[
        'python-dateutil',
        'oauth2client',
        'pytz',
        'pyxdg',
        'httplib2',
        'google-api-python-client',
        'simplejson',
        'pyopenssl',
        'twisted',
    ],
    entry_points={
        'console_scripts': [
            'snarf = logsnarf.app:main'
        ]
    }
)
