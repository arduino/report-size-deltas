# Frequently Asked Questions

## How can I work with sketches reports for multiple boards?

It is common for Arduino projects to target multiple boards. In this case, the sketch compilation job in the workflow should be configured to compile for each of the target boards in order to provide comprehensive coverage.

This can be accomplished in an easily maintainable and efficient manner by using a [matrix](https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions#jobsjob_idstrategymatrix) to generate a parallel workflow job for each board.

Each sketch compilation job will generate a [sketches report file](https://github.com/arduino/compile-sketches#sketches-report-path) containing the data the **arduino/report-size-deltas** action will use to produce the size deltas report comment. The sketches report file is passed from the sketch compilation job to the job containing the **arduino/report-size-deltas** step via a [workflow artifact](https://docs.github.com/actions/using-workflows/storing-workflow-data-as-artifacts).

### Size deltas report workflow triggered by `schedule` event

#### Sketch compilation workflow

```yaml
on:
  - push
  - pull_request

jobs:
  compile:
    runs-on: ubuntu-latest

    env:
      # It's convenient to set variables for values used multiple times in the workflow.
      SKETCHES_REPORTS_PATH: sketches-reports

    strategy:
      matrix:
        board:
          # Each element in the sequence produces a matrix job:
          - fqbn: arduino:avr:uno
            # This suffix will be used to define a unique name for the sketches report artifact.
            artifact-name-suffix: arduino-avr-uno
          - fqbn: arduino:samd:mkrzero
            artifact-name-suffix: arduino-samd-mkrzero

    steps:
      - uses: actions/checkout@v4

      - uses: arduino/compile-sketches@v1
        with:
          enable-deltas-report: true
          fqbn: ${{ matrix.board.fqbn }}
          sketches-report-path: ${{ env.SKETCHES_REPORTS_PATH }}

      - uses: actions/upload-artifact@v4
        with:
          # A fixed prefix on the artifact name allows the arduino/report-size-deltas action to identify the sketches
          # report artifacts.
          name: sketches-report-${{ matrix.board.artifact-name-suffix }}
          path: ${{ env.SKETCHES_REPORTS_PATH }}
```

#### Size deltas report workflow

```yaml
on:
  schedule:
    - cron: "*/5 * * * *"

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: arduino/report-size-deltas@v1
        with:
          # This regular expression matches names of sketches report artifacts produced by sketch compilation workflow.
          sketches-reports-source: ^sketches-report-.+
```

#### Overview of sketches report data flow

```mermaid
%%{
  init: {
    'flowchart': {
      'curve': 'basis'
    },
    'theme': 'base',
    'themeVariables': {
      'clusterBkg': '#ffffff',
      'edgeLabelBackground': '#ffffff',
      'lineColor': '#000000',
      'primaryBorderColor': '#000000',
      'primaryColor': '#f0f0f0',
      'primaryTextColor': '#000000'
    }
  }
}%%

flowchart TB
  subgraph main[" "]
    direction TB

    subgraph compileWorkflow["<b>Sketch compilation workflow run</b>"]
      direction TB

      unoJob["arduino:avr:uno<br />job"]
      mkrzeroJob["arduino:samd:mkrzero<br />job"]

      unoCompile["arduino/compile-sketches<br />action"]
      mkrzeroCompile["arduino/compile-sketches<br />action"]

      unoReportFile["arduino-avr-uno.json"]
      mkrzeroReportFile["arduino-samd-mkrzero.json"]

      unoUpload["actions/upload-artifact<br />action"]
      mkrzeroUpload["actions/upload-artifact<br />action"]

      unoArtifact["sketches-reports-arduino-avr-uno<br />artifact"]
      mkrzeroArtifact["sketches-reports-arduino-samd-mkrzero<br />artifact"]
    end

    subgraph reportWorkflow["<b>Size deltas report workflow run</b>"]
      direction TB

      reportAction["arduino/report-size-deltas<br />action"]
    end

    subgraph pr["<b>Pull request</b>"]
      direction TB

      comment["Size deltas report<br />comment"]
    end

    unoJob --> unoCompile
    mkrzeroJob --> mkrzeroCompile
    unoCompile --> unoReportFile
    mkrzeroCompile --> mkrzeroReportFile
    unoReportFile --> unoUpload
    mkrzeroReportFile --> mkrzeroUpload
    unoUpload --> unoArtifact
    mkrzeroUpload --> mkrzeroArtifact

    unoArtifact --> reportAction
    mkrzeroArtifact --> reportAction
    reportAction --> comment
  end
```
