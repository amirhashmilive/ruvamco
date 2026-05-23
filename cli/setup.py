from setuptools import setup, find_packages

setup(
    name="ruvamco-cli",
    version="1.0.0",
    author="Amir Hashmi",
    author_email="amir@ruvamco.io",
    description="RUVAMCO — Self-service edge proxy platform CLI",
    long_description=open("../README.md").read() if __import__("os").path.exists("../README.md") else "",
    long_description_content_type="text/markdown",
    url="https://github.com/amirhashmilive/ruvamco",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "click>=8.1,<9",
        "requests>=2.31,<3",
        "PyYAML>=6.0,<7",
        "tabulate>=0.9,<1",
        "rich>=13.0,<14",
    ],
    entry_points={
        "console_scripts": [
            "ruvamco=ruvamco.cli:cli",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet :: Proxy Servers",
        "Topic :: System :: Networking",
    ],
)
