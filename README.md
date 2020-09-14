# `arduino/report-size-deltas` action

[![Tests](https://github.com/arduino/report-size-deltas/workflows/libraries/report-size-deltas%20workflow/badge.svg)](https://github.com/arduino/report-size-deltas/actions?workflow=libraries/report-size-deltas+workflow)
[![Spell Check](https://github.com/arduino/report-size-deltas/workflows/Spell%20Check/badge.svg)](https://github.com/arduino/report-size-deltas/actions?workflow=Spell+Check)
[![codecov](https://codecov.io/gh/arduino/report-size-deltas/branch/master/graph/badge.svg)](https://codecov.io/gh/arduino/report-size-deltas)

This action comments on the pull request with a report on the resulting change in memory usage of the [Arduino](https://www.arduino.cc/) sketches compiled by the [`arduino/compile-sketches`](https://github.com/arduino/compile-sketches) action. This should be run from a [scheduled workflow](https://help.github.com/en/actions/reference/workflow-syntax-for-github-actions#onschedule).

## Inputs

### `size-deltas-reports-artifact-name`

Name of the [workflow artifact](https://docs.github.com/en/actions/configuring-and-managing-workflows/persisting-workflow-data-using-artifacts) that contains the memory usage data, as specified to the [`actions/upload-artifact`](https://github.com/actions/upload-artifact) action via its `name` input.

**Default**: `"size-deltas-reports"`

### `github-token`

[GitHub access token](https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token) used to comment the memory usage comparison results to the PR thread.

**Default**: [`GITHUB_TOKEN`](https://help.github.com/en/actions/configuring-and-managing-workflows/authenticating-with-the-github_token)

## Example usage

```yaml
on:
  schedule:
    - cron:  '*/5 * * * *'
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: arduino/report-size-deltas@main
```

This must be used in conjunction with a workflow that runs the [`arduino/compile-sketches`](https://github.com/arduino/compile-sketches) action and uploads the resulting sketches report to a [workflow artifact](https://help.github.com/en/actions/configuring-and-managing-workflows/persisting-workflow-data-using-artifacts):
```yaml
on: [push, pull_request]
jobs:
  compile:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: arduino/compile-sketches@main
        with:
          enable-deltas-report: true
      - uses: actions/upload-artifact@v2
        with:
          name: size-deltas-reports
          path: size-deltas-reports
```
