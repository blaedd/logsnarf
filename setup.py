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
    url='https://github.com/blaedd/logsnarf',
    license='MIT',
    author='David MacKinnon',
    author_email='blaedd@gmail.com',
    description='Tool to stream log files to BigQuery',
    tests_require=['mock', 'setuptools-trial'],
    setup_requires=['Sphinx', 'sphinx-rtd-theme'],
    python_requires='<3',
    install_requires=[
        'arrow',
        'cryptography<=3.3.2',
        'googleapis-common-protos',
        'python-dateutil',
        'oauth2client',
        'pathlib',
        'protobuf',
        'pytz',
        'pyxdg',
        'rsa<4.6',
        'requests',
        'httplib2',
        'google-api-python-client<2',
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
