#!/usr/bin/env python3
"""Setup script for Options Wheel Strategy package."""

from setuptools import setup, find_packages
import os

# Read README for long description
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# Read requirements
def read_requirements(filename):
    """Read requirements from file."""
    with open(filename, 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#') and not line.startswith('-r')]

# Core requirements
install_requires = read_requirements('requirements-minimal.txt')

# Optional requirements
extras_require = {
    'full': read_requirements('requirements.txt'),
    'dev': read_requirements('requirements-dev.txt'),
    'viz': [
        'matplotlib>=3.7.0',
        'seaborn>=0.12.0',
        'plotly>=5.17.0',
        'streamlit>=1.28.0'
    ],
    'analysis': [
        'jupyter>=1.0.0',
        'statsmodels>=0.14.0',
        'ta-lib>=0.4.28;platform_system!="Windows"',
        'quantlib>=1.32.0;platform_system!="Windows"'
    ]
}

setup(
    name="options-wheel-strategy",
    version="1.0.0",
    author="Options Wheel Trader",
    author_email="trader@example.com",
    description="Algorithmic options wheel strategy trading system with backtesting",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/username/options-wheel-strategy",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "Topic :: Office/Business :: Financial :: Investment",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.9",
    install_requires=install_requires,
    extras_require=extras_require,
    entry_points={
        "console_scripts": [
            "options-wheel=main:main",
            "wheel-backtest=backtest_runner:main",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["config/*.yaml", "*.md"],
    },
    zip_safe=False,
)