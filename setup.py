from setuptools import find_packages, setup

setup(
    name='serverwamp',
    version='0.2.0',
    description=('Components that add Web Application Messaging Protocol '
                 'features to WebSocket servers.'),
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    classifiers=(
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Internet',
        'Framework :: AsyncIO',
        'Framework :: Trio',
    ),
    install_requires=(
        'dataclasses~=0.6;python_version<"3.7"'
    ),
    keywords=(
        'WAMP', 'WebSockets', 'aiohttp', 'RPC', 'pubsub', 'broker', 'dealer',
        'ASGI'
    ),
    python_requires=">=3.6",
    author='Justin Turner Arthur',
    author_email='justinarthur@gmail.com',
    url='https://github.com/JustinTArthur/serverwamp',
    license='MIT',
    packages=find_packages(exclude=('tests',)),
    package_data={
        'serverwamp': ('py.typed',),
    },
)
