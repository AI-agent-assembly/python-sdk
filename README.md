# Agent Assembly Python SDK

## Overview

The Agent Assembly Python SDK provides a governance-native runtime for AI agents. This SDK enables developers to integrate AI agent lifecycle management, policy enforcement, and audit logging into their applications. It follows a WebAssembly-like pattern with a Rust core runtime and Python client interface.


## Python versions support

🚧 The required Python versions of this library

[![Supported Versions](https://img.shields.io/pypi/pyversions/<you lib name>.svg?logo=python&logoColor=FBE072)](https://pypi.org/project/<you lib name>)


## Quickly Start

🚧 The details of quickly start as simple demonstration for users

## Documentation

🚧 The details of documentation ...

## Reusable GitHub Actions Workflows & Actions

This template provides a comprehensive set of **reusable GitHub Actions workflows and actions** that can be called from other repositories to standardize CI/CD operations. Projects using this template can leverage these centralized components for consistent automation.

### 🚀 Key Features

- **Centralized Management**: All workflows and actions are maintained in this template repository
- **Standardized Operations**: Consistent CI/CD processes across all projects
- **Easy Integration**: Simple calls using external repository references
- **Comprehensive Coverage**: Testing, building, releasing, Docker operations, documentation, and setup utilities

### 📋 Available Workflows

| Workflow                                             | Purpose                      | Key Features                           |
|------------------------------------------------------|------------------------------|----------------------------------------|
| `rw_build_and_test.yaml`                             | Run comprehensive test suite | Unit, integration, e2e, contract tests |
| `rw_run_all_test_and_record.yaml`                    | Complete CI with reporting   | CodeCov upload, SonarCloud analysis    |
| `rw_python_package.yaml`                             | Python package operations    | Build, test, publish to PyPI           |
| `rw_docker_operations.yaml`                          | Docker operations            | Build, test, push, security scanning   |
| `rw_parse_release_intent.yaml`                       | Release configuration parser | Determines release components          |
| `rw_build_git-tag_and_create_github-release_v2.yaml` | Git tagging and releases     | Automated version management           |
| `rw_docs_operations.yaml`                            | Documentation operations     | Build, version, deploy docs            |

### 📦 Available Actions

| Action | Purpose | Key Features |
|--------|---------|--------------|
| `setup-python-uv` | Python & UV setup with dependencies | Multi-version support, intelligent caching, flexible dependency groups |

### 🔧 Quick Start

To use these reusable workflows in your project, simply call them using external repository references:

```yaml
# .github/workflows/ci.yaml in your project
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    uses: Chisanan232/Template-Python-UV-Project/.github/workflows/rw_run_all_test_and_record.yaml@master
    secrets:
      codecov_token: ${{ secrets.CODECOV_TOKEN }}
      sonar_token: ${{ secrets.SONAR_TOKEN }}
```

### 📚 Complete Documentation

- **[Reusable Workflows Guide](.github/workflows/REUSABLE_WORKFLOWS.md)**: Complete documentation with all inputs, outputs, and usage examples
- **[Example Workflows](.github/workflows/examples/)**: Ready-to-use example workflows for common scenarios
- **Template Placeholders**: All workflows use `<your_*>` placeholders for easy customization

### 💡 Benefits for Projects Using This Template

1. **Reduced Boilerplate**: No need to write complex CI/CD workflows from scratch
2. **Best Practices**: Workflows follow established patterns and security practices  
3. **Automatic Updates**: Bug fixes and improvements are centrally maintained
4. **Consistency**: Same workflow behavior across all projects using the template
5. **Easy Maintenance**: Update workflows in one place, benefits all projects


## Coding style and following rules

**_<your lib name>_** follows coding styles **_black_** and **_PyLint_** to control code quality.

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![linting: pylint](https://img.shields.io/badge/linting-pylint-yellowgreen)](https://github.com/pylint-dev/pylint)


## Downloading state

🚧 The download state for your library

[![Downloads](https://pepy.tech/badge/<your lib name>)](https://pepy.tech/project/<your lib name>)
[![Downloads](https://pepy.tech/badge/<your lib name>/month)](https://pepy.tech/project/<your lib name>)


## License

[MIT License](./LICENSE)
