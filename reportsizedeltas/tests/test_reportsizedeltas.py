import distutils.dir_util
import filecmp
import json
import os
import pathlib
import tempfile
import unittest.mock
import urllib
import zipfile

import pytest

import reportsizedeltas

reportsizedeltas.set_verbosity(enable_verbosity=False)

test_data_path = pathlib.Path(__file__).resolve().parent.joinpath("data")
report_keys = reportsizedeltas.ReportSizeDeltas.ReportKeys()


def get_reportsizedeltas_object(
    repository_name: str = "FooOwner/BarRepository",
    sketches_reports_source: str = "foo-artifact-pattern",
    token: str = "foo token",
) -> reportsizedeltas.ReportSizeDeltas:
    """Return a reportsizedeltas.ReportSizeDeltas object to use in tests.

    Keyword arguments:
    repository_name -- repository owner and name e.g., octocat/Hello-World
    sketches_reports_source -- regular expression for the names of the workflow artifacts that contain the memory usage
                               data
    token -- GitHub access token
    """
    return reportsizedeltas.ReportSizeDeltas(
        repository_name=repository_name, sketches_reports_source=sketches_reports_source, token=token
    )


def directories_are_same(left_directory, right_directory) -> bool:
    """Check recursively whether two directories contain the same files.
    Based on https://stackoverflow.com/a/6681395

    Keyword arguments:
    left_directory -- one of the two directories to compare
    right_directory -- the other directory to compare
    """
    filecmp.clear_cache()
    directory_comparison = filecmp.dircmp(a=left_directory, b=right_directory)
    if (
        len(directory_comparison.left_only) > 0
        or len(directory_comparison.right_only) > 0
        or len(directory_comparison.funny_files) > 0
    ):
        return False

    filecmp.clear_cache()
    (_, mismatch, errors) = filecmp.cmpfiles(
        a=left_directory, b=right_directory, common=directory_comparison.common_files, shallow=False
    )
    if len(mismatch) > 0 or len(errors) > 0:
        return False

    for common_dir in directory_comparison.common_dirs:
        if not directories_are_same(
            left_directory=left_directory.joinpath(common_dir), right_directory=right_directory.joinpath(common_dir)
        ):
            return False

    return True


def test_directories_are_same(tmp_path):
    left_directory = tmp_path.joinpath("left_directory")
    right_directory = tmp_path.joinpath("right_directory")
    left_directory.mkdir()
    right_directory.mkdir()

    # Different directory contents
    left_directory.joinpath("foo.txt").write_text(data="foo")
    assert directories_are_same(left_directory=left_directory, right_directory=right_directory) is False

    # Different file contents
    right_directory.joinpath("foo.txt").write_text(data="bar")
    assert directories_are_same(left_directory=left_directory, right_directory=right_directory) is False

    # Different file contents in subdirectory
    right_directory.joinpath("foo.txt").write_text(data="foo")
    left_directory.joinpath("bar").mkdir()
    right_directory.joinpath("bar").mkdir()
    left_directory.joinpath("bar", "bar.txt").write_text(data="foo")
    right_directory.joinpath("bar", "bar.txt").write_text(data="bar")
    assert directories_are_same(left_directory=left_directory, right_directory=right_directory) is False

    right_directory.joinpath("bar", "bar.txt").write_text(data="foo")
    assert directories_are_same(left_directory=left_directory, right_directory=right_directory) is True


@pytest.fixture
def setup_environment_variables(monkeypatch):
    """Test fixture that sets up the environment variables required by reportsizedeltas.main() and returns an object
    containing the values"""

    class ActionInputs:
        """A container for the values of the environment variables"""

        repository_name = "GoldenOwner/GoldenRepository"
        sketches_reports_source = "golden-source-pattern"
        token = "golden-github-token"

    monkeypatch.setenv("GITHUB_REPOSITORY", ActionInputs.repository_name)
    monkeypatch.setenv("INPUT_SKETCHES-REPORTS-SOURCE", ActionInputs.sketches_reports_source)
    monkeypatch.setenv("INPUT_GITHUB-TOKEN", ActionInputs.token)

    return ActionInputs()


def test_main(monkeypatch, mocker, setup_environment_variables):
    class ReportSizeDeltas:
        """Stub"""

        def report_size_deltas(self):
            """Stub"""
            pass  # pragma: no cover

    mocker.patch("reportsizedeltas.set_verbosity", autospec=True)
    mocker.patch("reportsizedeltas.ReportSizeDeltas", autospec=True, return_value=ReportSizeDeltas())
    mocker.patch.object(ReportSizeDeltas, "report_size_deltas")
    reportsizedeltas.main()

    reportsizedeltas.set_verbosity.assert_called_once_with(enable_verbosity=False)
    reportsizedeltas.ReportSizeDeltas.assert_called_once_with(
        repository_name=setup_environment_variables.repository_name,
        sketches_reports_source=setup_environment_variables.sketches_reports_source,
        token=setup_environment_variables.token,
    )
    ReportSizeDeltas.report_size_deltas.assert_called_once()


@pytest.mark.parametrize("use_size_deltas_report_artifact_name", [True, False])
def test_main_size_deltas_report_artifact_name_deprecation_warning(
    capsys, mocker, monkeypatch, setup_environment_variables, use_size_deltas_report_artifact_name
):
    size_deltas_report_artifact_pattern = "golden-size-deltas-report-artifact-name-value"

    if use_size_deltas_report_artifact_name:
        monkeypatch.setenv("INPUT_SIZE-DELTAS-REPORTS-ARTIFACT-NAME", size_deltas_report_artifact_pattern)
        expected_sketches_reports_source = size_deltas_report_artifact_pattern
    else:
        expected_sketches_reports_source = setup_environment_variables.sketches_reports_source

    class ReportSizeDeltas:
        """Stub"""

        def report_size_deltas(self):
            """Stub"""
            pass  # pragma: no cover

    mocker.patch("reportsizedeltas.set_verbosity", autospec=True)
    mocker.patch("reportsizedeltas.ReportSizeDeltas", autospec=True, return_value=ReportSizeDeltas())
    mocker.patch.object(ReportSizeDeltas, "report_size_deltas")

    reportsizedeltas.main()

    expected_output = ""
    if use_size_deltas_report_artifact_name:
        expected_output = (
            expected_output
            + "::warning::The size-deltas-report-artifact-name input is deprecated. Use the equivalent input: "
            "sketches-reports-source instead."
        )

    assert capsys.readouterr().out.strip() == expected_output

    assert os.environ["INPUT_SKETCHES-REPORTS-SOURCE"] == expected_sketches_reports_source


def test_set_verbosity():
    with pytest.raises(TypeError):
        reportsizedeltas.set_verbosity(enable_verbosity=2)
    reportsizedeltas.set_verbosity(enable_verbosity=True)
    reportsizedeltas.set_verbosity(enable_verbosity=False)


# noinspection PyUnresolvedReferences
def test_report_size_deltas(mocker, monkeypatch):
    mocker.patch("reportsizedeltas.ReportSizeDeltas.report_size_deltas_from_local_reports", autospec=True)
    mocker.patch("reportsizedeltas.ReportSizeDeltas.report_size_deltas_from_workflow_artifacts", autospec=True)

    report_size_deltas = get_reportsizedeltas_object()

    # Test triggered by pull_request event
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    report_size_deltas.report_size_deltas()
    # noinspection PyUnresolvedReferences
    report_size_deltas.report_size_deltas_from_local_reports.assert_called_once()
    report_size_deltas.report_size_deltas_from_workflow_artifacts.assert_not_called()

    # Test triggered by other than pull_request event
    mocker.resetall()
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    report_size_deltas.report_size_deltas()
    report_size_deltas.report_size_deltas_from_local_reports.assert_not_called()
    report_size_deltas.report_size_deltas_from_workflow_artifacts.assert_called_once()


def test_report_size_deltas_from_local_reports(mocker, monkeypatch):
    sketches_reports_source = "golden-sketches-reports-source-path"
    github_workspace = "golden-github-workspace"
    sketches_reports_folder = pathlib.Path(github_workspace, sketches_reports_source)
    sketches_reports = unittest.mock.sentinel.sketches_reports
    report = "golden report"

    monkeypatch.setenv("GITHUB_WORKSPACE", github_workspace)
    monkeypatch.setenv(
        "GITHUB_EVENT_PATH", str(test_data_path.joinpath("test_report_size_deltas_pull_request", "githubevent.json"))
    )

    mocker.patch("reportsizedeltas.ReportSizeDeltas.get_sketches_reports", autospec=True)
    mocker.patch("reportsizedeltas.ReportSizeDeltas.generate_report", autospec=True, return_value=report)
    mocker.patch("reportsizedeltas.ReportSizeDeltas.comment_report", autospec=True)

    report_size_deltas = get_reportsizedeltas_object(sketches_reports_source=sketches_reports_source)

    # Test handling of no sketches reports data available
    reportsizedeltas.ReportSizeDeltas.get_sketches_reports.return_value = None
    report_size_deltas.report_size_deltas_from_local_reports()

    report_size_deltas.comment_report.assert_not_called()

    # Test report data available
    mocker.resetall()
    reportsizedeltas.ReportSizeDeltas.get_sketches_reports.return_value = sketches_reports
    report_size_deltas.report_size_deltas_from_local_reports()

    report_size_deltas.get_sketches_reports.assert_called_once_with(
        report_size_deltas, artifacts_folder_object=sketches_reports_folder
    )
    report_size_deltas.generate_report.assert_called_once_with(report_size_deltas, sketches_reports=sketches_reports)
    report_size_deltas.comment_report.assert_called_once_with(report_size_deltas, pr_number=42, report_markdown=report)


def test_report_size_deltas_from_workflow_artifacts(mocker):
    artifacts_data = unittest.mock.sentinel.artifacts_data
    artifacts_folder_object = "test_artifacts_folder_object"
    pr_head_sha = "pr-head-sha"
    sketches_reports = [{reportsizedeltas.ReportSizeDeltas.ReportKeys.commit_hash: pr_head_sha}]
    report = "foo report"
    json_data = [
        {"number": 1, "locked": True, "head": {"sha": pr_head_sha, "ref": "asdf"}, "user": {"login": "1234"}},
        {"number": 2, "locked": False, "head": {"sha": pr_head_sha, "ref": "asdf"}, "user": {"login": "1234"}},
    ]

    report_size_deltas = get_reportsizedeltas_object()

    mocker.patch(
        "reportsizedeltas.ReportSizeDeltas.api_request",
        autospec=True,
        return_value={"json_data": json_data, "additional_pages": True, "page_count": 1},
    )
    mocker.patch("reportsizedeltas.ReportSizeDeltas.report_exists", autospec=True, return_value=False)
    mocker.patch(
        "reportsizedeltas.ReportSizeDeltas.get_artifacts_data_for_sha",
        autospec=True,
        return_value=artifacts_data,
    )
    mocker.patch("reportsizedeltas.ReportSizeDeltas.get_artifacts", autospec=True, return_value=artifacts_folder_object)
    mocker.patch("reportsizedeltas.ReportSizeDeltas.get_sketches_reports", autospec=True, return_value=sketches_reports)
    mocker.patch("reportsizedeltas.ReportSizeDeltas.generate_report", autospec=True, return_value=report)
    mocker.patch("reportsizedeltas.ReportSizeDeltas.comment_report", autospec=True)

    # Test handling of locked PR
    mocker.resetall()

    report_size_deltas.report_size_deltas_from_workflow_artifacts()

    report_size_deltas.comment_report.assert_called_once_with(report_size_deltas, pr_number=2, report_markdown=report)

    # Test handling of existing reports
    for pr_data in json_data:
        pr_data["locked"] = False
    reportsizedeltas.ReportSizeDeltas.report_exists.return_value = True
    mocker.resetall()

    report_size_deltas.report_size_deltas_from_workflow_artifacts()

    report_size_deltas.comment_report.assert_not_called()

    # Test handling of no report artifact
    reportsizedeltas.ReportSizeDeltas.report_exists.return_value = False
    reportsizedeltas.ReportSizeDeltas.get_artifacts_data_for_sha.return_value = None
    mocker.resetall()

    report_size_deltas.report_size_deltas_from_workflow_artifacts()

    report_size_deltas.comment_report.assert_not_called()

    # Test handling of old sketches report artifacts
    reportsizedeltas.ReportSizeDeltas.get_artifacts_data_for_sha.return_value = artifacts_data
    reportsizedeltas.ReportSizeDeltas.get_sketches_reports.return_value = None
    mocker.resetall()

    report_size_deltas.report_size_deltas_from_workflow_artifacts()

    report_size_deltas.comment_report.assert_not_called()

    # Test API/report hash mismatch
    sketches_reports = [{reportsizedeltas.ReportSizeDeltas.ReportKeys.commit_hash: "mismatched-hash"}]

    reportsizedeltas.ReportSizeDeltas.get_sketches_reports.return_value = sketches_reports

    mocker.resetall()

    report_size_deltas.report_size_deltas_from_workflow_artifacts()

    report_size_deltas.comment_report.assert_not_called()

    # Test making reports
    sketches_reports = [{reportsizedeltas.ReportSizeDeltas.ReportKeys.commit_hash: pr_head_sha}]
    reportsizedeltas.ReportSizeDeltas.get_sketches_reports.return_value = sketches_reports
    mocker.resetall()

    report_size_deltas.report_size_deltas_from_workflow_artifacts()

    report_exists_calls = []
    get_artifacts_data_for_sha_calls = []
    get_sketches_reports_calls = []
    generate_report_calls = []
    comment_report_calls = []
    for pr_data in json_data:
        report_exists_calls.append(
            unittest.mock.call(report_size_deltas, pr_number=pr_data["number"], pr_head_sha=json_data[0]["head"]["sha"])
        )
        get_artifacts_data_for_sha_calls.append(
            unittest.mock.call(
                report_size_deltas,
                pr_user_login=pr_data["user"]["login"],
                pr_head_ref=pr_data["head"]["ref"],
                pr_head_sha=pr_data["head"]["sha"],
            )
        )
        get_sketches_reports_calls.append(
            unittest.mock.call(report_size_deltas, artifacts_folder_object=artifacts_folder_object)
        )
        generate_report_calls.append(unittest.mock.call(report_size_deltas, sketches_reports=sketches_reports))
        comment_report_calls.append(
            unittest.mock.call(report_size_deltas, pr_number=pr_data["number"], report_markdown=report)
        )
    report_size_deltas.report_exists.assert_has_calls(calls=report_exists_calls)
    report_size_deltas.get_artifacts_data_for_sha.assert_has_calls(calls=get_artifacts_data_for_sha_calls)
    report_size_deltas.get_artifacts.assert_called_with(report_size_deltas, artifacts_data=artifacts_data)
    report_size_deltas.get_sketches_reports.assert_has_calls(calls=get_sketches_reports_calls)
    report_size_deltas.generate_report.assert_has_calls(calls=generate_report_calls)
    report_size_deltas.comment_report.assert_has_calls(calls=comment_report_calls)


def test_report_exists():
    repository_name = "test_name/test_repo"
    pr_number = 42
    pr_head_sha = "foo123"

    report_size_deltas = get_reportsizedeltas_object(repository_name=repository_name)

    json_data = [{"body": "foo123"}, {"body": report_size_deltas.report_key_beginning + pr_head_sha + "foo"}]
    report_size_deltas.api_request = unittest.mock.MagicMock(
        return_value={"json_data": json_data, "additional_pages": False, "page_count": 1}
    )

    assert report_size_deltas.report_exists(pr_number=pr_number, pr_head_sha=pr_head_sha)

    report_size_deltas.api_request.assert_called_once_with(
        request="repos/" + repository_name + "/issues/" + str(pr_number) + "/comments", page_number=1
    )

    assert not report_size_deltas.report_exists(pr_number=pr_number, pr_head_sha="asdf")


def test_get_artifacts_data_for_sha():
    repository_name = "test_name/test_repo"
    pr_user_login = "test_pr_user_login"
    pr_head_ref = "test_pr_head_ref"
    pr_head_sha = "bar123"
    test_artifacts_data = unittest.mock.sentinel.artifacts_data
    run_id = "4567"

    report_size_deltas = get_reportsizedeltas_object(repository_name=repository_name)

    json_data = {"workflow_runs": [{"head_sha": "foo123", "id": "1234"}, {"head_sha": pr_head_sha, "id": run_id}]}
    report_size_deltas.api_request = unittest.mock.MagicMock(
        return_value={"json_data": json_data, "additional_pages": True, "page_count": 3}
    )
    report_size_deltas.get_artifacts_data_for_run = unittest.mock.MagicMock(return_value=None)

    # No SHA match
    assert (
        report_size_deltas.get_artifacts_data_for_sha(
            pr_user_login=pr_user_login, pr_head_ref=pr_head_ref, pr_head_sha="foosha"
        )
        is None
    )

    # Test pagination
    request = "repos/" + repository_name + "/actions/runs"
    request_parameters = "actor=" + pr_user_login + "&branch=" + pr_head_ref + "&event=pull_request&status=completed"
    calls = [
        unittest.mock.call(request=request, request_parameters=request_parameters, page_number=1),
        unittest.mock.call(request=request, request_parameters=request_parameters, page_number=2),
        unittest.mock.call(request=request, request_parameters=request_parameters, page_number=3),
    ]
    report_size_deltas.api_request.assert_has_calls(calls)

    # SHA match, but no artifact for run
    assert (
        report_size_deltas.get_artifacts_data_for_sha(
            pr_user_login=pr_user_login, pr_head_ref=pr_head_ref, pr_head_sha=pr_head_sha
        )
        is None
    )

    report_size_deltas.get_artifacts_data_for_run = unittest.mock.MagicMock(return_value=test_artifacts_data)

    # SHA match, artifact match
    assert test_artifacts_data == (
        report_size_deltas.get_artifacts_data_for_sha(
            pr_user_login=pr_user_login, pr_head_ref=pr_head_ref, pr_head_sha=pr_head_sha
        )
    )

    report_size_deltas.get_artifacts_data_for_run.assert_called_once_with(run_id=run_id)


@pytest.mark.parametrize(
    "sketches_reports_source, artifacts_data, report_artifacts_data_assertion",
    [
        # Expired artifact
        ("artifact-name", [{"expired": True, "name": "artifact-name"}], None),
        # No artifacts
        ("foo", [], None),
        # Pattern is explicit artifact name
        ("artifact-name", [{"expired": False, "name": "artifact-name"}], [{"expired": False, "name": "artifact-name"}]),
        # Pattern is regular expression
        (
            "^artifact-prefix-.+",
            [
                {"expired": False, "name": "artifact-prefix-foo"},
                {"expired": False, "name": "artifact-prefix-bar"},
                {"expired": False, "name": "mismatch"},
            ],
            [{"expired": False, "name": "artifact-prefix-foo"}, {"expired": False, "name": "artifact-prefix-bar"}],
        ),
    ],
)
def test_get_artifacts_data_for_run(sketches_reports_source, artifacts_data, report_artifacts_data_assertion):
    repository_name = "test_name/test_repo"
    run_id = "1234"

    report_size_deltas = get_reportsizedeltas_object(
        repository_name=repository_name, sketches_reports_source=sketches_reports_source
    )

    json_data = {"artifacts": artifacts_data}
    report_size_deltas.api_request = unittest.mock.MagicMock(
        return_value={"json_data": json_data, "additional_pages": False, "page_count": 1}
    )

    assert report_size_deltas.get_artifacts_data_for_run(run_id=run_id) == report_artifacts_data_assertion

    report_size_deltas.api_request.assert_called_once_with(
        request="repos/" + repository_name + "/actions/runs/" + str(run_id) + "/artifacts", page_number=1
    )


@pytest.mark.parametrize("artifacts_testdata", ["multiple-artifacts", "single-artifact"])
def test_get_artifacts_success(tmp_path, artifacts_testdata):
    artifacts_data = []

    # Create archive files
    artifacts_source_path = test_data_path.joinpath("test_get_artifacts", artifacts_testdata)
    artifact_destination_path = tmp_path.joinpath("url_path")
    artifact_destination_path.mkdir()
    for artifact_source_path in artifacts_source_path.iterdir():
        artifact_name = artifact_source_path.name
        artifact_archive_destination_path = artifact_destination_path.joinpath(artifact_name + ".zip")
        with zipfile.ZipFile(file=artifact_archive_destination_path, mode="a") as zip_ref:
            for artifact_file in artifact_source_path.rglob("*"):
                zip_ref.write(filename=artifact_file, arcname=artifact_file.relative_to(artifact_source_path))

        artifacts_data.append(
            {
                "archive_download_url": artifact_destination_path.joinpath(artifact_name + ".zip").as_uri(),
                "name": artifact_name,
            }
        )

    report_size_deltas = get_reportsizedeltas_object()

    artifacts_folder_object = report_size_deltas.get_artifacts(artifacts_data=artifacts_data)

    with artifacts_folder_object as artifacts_folder:
        # Verify that the artifact matches the source
        assert directories_are_same(
            left_directory=artifacts_source_path, right_directory=pathlib.Path(artifacts_folder)
        )


def test_get_artifacts_failure():
    artifacts_data = [
        {
            "archive_download_url": "http://httpstat.us/404",
            "name": "artifact_name",
        }
    ]

    report_size_deltas = get_reportsizedeltas_object()

    with pytest.raises(expected_exception=urllib.error.URLError):
        report_size_deltas.get_artifacts(artifacts_data=artifacts_data)


@pytest.mark.parametrize(
    "test_data_folder_name",
    ["old-report-format", "single-artifact", "multiple-artifacts", "artifact-contains-folder"],
)
def test_get_sketches_reports(test_data_folder_name):
    current_test_data_path = test_data_path.joinpath("test_get_sketches_reports", test_data_folder_name)
    report_size_deltas = get_reportsizedeltas_object()

    artifacts_folder_object = tempfile.TemporaryDirectory(prefix="test_reportsizedeltas-")
    try:
        distutils.dir_util.copy_tree(
            src=str(current_test_data_path.joinpath("artifacts")), dst=artifacts_folder_object.name
        )
    except Exception:  # pragma: no cover
        artifacts_folder_object.cleanup()
        raise
    sketches_reports = report_size_deltas.get_sketches_reports(artifacts_folder_object=artifacts_folder_object)

    with open(file=current_test_data_path.joinpath("golden-sketches-reports.json")) as golden_sketches_reports_file:
        assert sketches_reports == json.load(golden_sketches_reports_file)


@pytest.mark.parametrize(
    "report_data, fqbn_data, expected_report_data",
    [
        (
            [["Board"]],
            {
                report_keys.board: "arduino:avr:uno",
                report_keys.sizes: [
                    {
                        report_keys.delta: {
                            report_keys.absolute: {report_keys.maximum: -994, report_keys.minimum: -994},
                            report_keys.relative: {report_keys.maximum: -3.08, report_keys.minimum: -3.08},
                        },
                        report_keys.name: "flash",
                        report_keys.maximum: 32256,
                    },
                    {
                        report_keys.delta: {
                            report_keys.absolute: {report_keys.maximum: -175, report_keys.minimum: -175},
                            report_keys.relative: {report_keys.maximum: -8.54, report_keys.minimum: -8.54},
                        },
                        report_keys.name: "RAM for global variables",
                        report_keys.maximum: 2048,
                    },
                ],
            },
            [
                ["Board", "flash", "%", "RAM for global variables", "%"],
                [
                    "`arduino:avr:uno`",
                    ":green_heart: -994 - -994",
                    "-3.08 - -3.08",
                    ":green_heart: -175 - -175",
                    "-8.54 - -8.54",
                ],
            ],
        ),
        (
            [
                ["Board", "flash", "%", "RAM for global variables", "%"],
                [
                    "`arduino:avr:uno`",
                    ":green_heart: -994 - -994",
                    "-3.08 - -3.08",
                    ":green_heart: -175 - -175",
                    "-8.54 - -8.54",
                ],
            ],
            {
                report_keys.board: "arduino:mbed_portenta:envie_m7",
                report_keys.sizes: [
                    {
                        report_keys.name: "flash",
                        report_keys.maximum: "N/A",
                    },
                    {
                        report_keys.name: "RAM for global variables",
                        report_keys.maximum: "N/A",
                    },
                ],
            },
            [
                ["Board", "flash", "%", "RAM for global variables", "%"],
                [
                    "`arduino:avr:uno`",
                    ":green_heart: -994 - -994",
                    "-3.08 - -3.08",
                    ":green_heart: -175 - -175",
                    "-8.54 - -8.54",
                ],
                ["`arduino:mbed_portenta:envie_m7`", "N/A", "N/A", "N/A", "N/A"],
            ],
        ),
    ],
)
def test_add_summary_report_row(report_data, fqbn_data, expected_report_data):
    report_size_deltas = get_reportsizedeltas_object()
    report_size_deltas.add_summary_report_row(report_data, fqbn_data)

    assert report_data == expected_report_data


@pytest.mark.parametrize(
    "report_data, fqbn_data, expected_report_data",
    [
        (
            [["Board"]],
            {
                report_keys.board: "arduino:avr:leonardo",
                report_keys.sketches: [
                    {
                        report_keys.compilation_success: True,
                        report_keys.name: "examples/Foo",
                        report_keys.sizes: [
                            {
                                report_keys.current: {report_keys.absolute: 3462, report_keys.relative: 12.07},
                                report_keys.delta: {report_keys.absolute: -12, report_keys.relative: -0.05},
                                report_keys.name: "flash",
                                report_keys.maximum: 28672,
                                report_keys.previous: {report_keys.absolute: 3474, report_keys.relative: 12.12},
                            },
                            {
                                report_keys.current: {report_keys.absolute: 149, report_keys.relative: 5.82},
                                report_keys.delta: {report_keys.absolute: 0, report_keys.relative: -0.00},
                                report_keys.name: "RAM for global variables",
                                report_keys.maximum: 2560,
                                report_keys.previous: {report_keys.absolute: 149, report_keys.relative: 5.82},
                            },
                        ],
                    }
                ],
            },
            [
                ["Board", "`examples/Foo`<br>flash", "%", "`examples/Foo`<br>RAM for global variables", "%"],
                ["`arduino:avr:leonardo`", -12, -0.05, 0, -0.0],
            ],
        ),
        (
            [
                ["Board", "`examples/Foo`<br>flash", "%", "`examples/Foo`<br>RAM for global variables", "%"],
                ["`arduino:avr:leonardo`", -12, -0.05, 0, -0.0],
            ],
            {
                report_keys.board: "arduino:mbed_portenta:envie_m7",
                report_keys.sketches: [
                    {
                        report_keys.compilation_success: True,
                        report_keys.name: "examples/Foo",
                        report_keys.sizes: [
                            {
                                report_keys.current: {report_keys.absolute: "N/A", report_keys.relative: "N/A"},
                                report_keys.name: "flash",
                                report_keys.maximum: "N/A",
                            },
                            {
                                report_keys.current: {report_keys.absolute: "N/A", report_keys.relative: "N/A"},
                                report_keys.name: "RAM for global variables",
                                report_keys.maximum: "N/A",
                            },
                        ],
                    }
                ],
            },
            [
                ["Board", "`examples/Foo`<br>flash", "%", "`examples/Foo`<br>RAM for global variables", "%"],
                ["`arduino:avr:leonardo`", -12, -0.05, 0, -0.0],
                ["`arduino:mbed_portenta:envie_m7`", "N/A", "N/A", "N/A", "N/A"],
            ],
        ),
    ],
)
def test_add_detailed_report_row(report_data, fqbn_data, expected_report_data):
    report_size_deltas = get_reportsizedeltas_object()
    report_size_deltas.add_detailed_report_row(report_data, fqbn_data)

    assert report_data == expected_report_data


def test_generate_report():
    sketches_report_path = test_data_path.joinpath("size-deltas-reports-new")
    expected_deltas_report = (
        "**Memory usage change @ d8fd302**\n\n"
        "Board|flash|%|RAM for global variables|%\n"
        "-|-|-|-|-\n"
        "`arduino:avr:leonardo`|:green_heart: -12 - -12|-0.05 - -0.05|0 - 0|0.0 - 0.0\n"
        "`arduino:avr:uno`|:green_heart: -994 - -994|-3.08 - -3.08|:green_heart: -175 - -175|-8.54 - -8.54\n"
        "`arduino:mbed_portenta:envie_m7`|N/A|N/A|N/A|N/A\n\n"
        "<details>\n"
        "<summary>Click for full report table</summary>\n\n"
        "Board|`examples/Bar`<br>flash|%|`examples/Bar`<br>RAM for global variables|%|`examples/Foo`<br>flash|%|"
        "`examples/Foo`<br>RAM for global variables|%\n"
        "-|-|-|-|-|-|-|-|-\n"
        "`arduino:avr:leonardo`|N/A|N/A|N/A|N/A|-12|-0.05|0|0.0\n"
        "`arduino:avr:uno`|N/A|N/A|N/A|N/A|-994|-3.08|-175|-8.54\n"
        "`arduino:mbed_portenta:envie_m7`|N/A|N/A|N/A|N/A|N/A|N/A|N/A|N/A\n\n"
        "</details>\n\n"
        "<details>\n"
        "<summary>Click for full report CSV</summary>\n\n"
        "```\n"
        "Board,examples/Bar<br>flash,%,examples/Bar<br>RAM for global variables,%,examples/Foo<br>flash,%,examples/Foo"
        "<br>RAM for global variables,%\n"
        "arduino:avr:leonardo,N/A,N/A,N/A,N/A,-12,-0.05,0,0.0\n"
        "arduino:avr:uno,N/A,N/A,N/A,N/A,-994,-3.08,-175,-8.54\n"
        "arduino:mbed_portenta:envie_m7,N/A,N/A,N/A,N/A,N/A,N/A,N/A,N/A\n"
        "```\n"
        "</details>"
    )

    report_size_deltas = get_reportsizedeltas_object()

    artifacts_folder_object = tempfile.TemporaryDirectory(prefix="test_reportsizedeltas-")
    try:
        distutils.dir_util.copy_tree(src=str(sketches_report_path), dst=artifacts_folder_object.name)
    except Exception:  # pragma: no cover
        artifacts_folder_object.cleanup()
        raise
    sketches_reports = report_size_deltas.get_sketches_reports(artifacts_folder_object=artifacts_folder_object)

    report = report_size_deltas.generate_report(sketches_reports=sketches_reports)
    assert report == expected_deltas_report


@pytest.mark.parametrize(
    "show_emoji, minimum, maximum, expected_value",
    [
        (True, "N/A", "N/A", "N/A"),
        (True, -1, 0, ":green_heart: -1 - 0"),
        (False, -1, 0, "-1 - 0"),
        (True, 0, 0, "0 - 0"),
        (True, 0, 1, ":small_red_triangle: 0 - +1"),
        (True, 1, 1, ":small_red_triangle: +1 - +1"),
        (True, -1, 1, ":grey_question: -1 - +1"),
    ],
)
def test_get_summary_value(show_emoji, minimum, maximum, expected_value):
    report_size_deltas = get_reportsizedeltas_object()

    assert (
        report_size_deltas.get_summary_value(show_emoji=show_emoji, minimum=minimum, maximum=maximum) == expected_value
    )


def test_comment_report():
    pr_number = 42
    report_markdown = "test_report_markdown"
    repository_name = "test_user/test_repo"

    report_size_deltas = get_reportsizedeltas_object(repository_name=repository_name)

    report_size_deltas.http_request = unittest.mock.MagicMock()

    report_size_deltas.comment_report(pr_number=pr_number, report_markdown=report_markdown)

    report_data = {"body": report_markdown}
    report_data = json.dumps(obj=report_data)
    report_data = report_data.encode(encoding="utf-8")

    report_size_deltas.http_request.assert_called_once_with(
        url="https://api.github.com/repos/" + repository_name + "/issues/" + str(pr_number) + "/comments",
        data=report_data,
    )


def test_api_request():
    response_data = {"json_data": {"foo": "bar"}, "additional_pages": False, "page_count": 1}
    request = "test_request"
    request_parameters = "test_parameters"
    page_number = 1

    report_size_deltas = get_reportsizedeltas_object()

    report_size_deltas.get_json_response = unittest.mock.MagicMock(return_value=response_data)

    assert response_data == report_size_deltas.api_request(
        request=request, request_parameters=request_parameters, page_number=page_number
    )
    report_size_deltas.get_json_response.assert_called_once_with(
        url="https://api.github.com/"
        + request
        + "?"
        + request_parameters
        + "&page="
        + str(page_number)
        + "&per_page=100"
    )


def test_get_json_response():
    url = "test_url"

    report_size_deltas = get_reportsizedeltas_object()

    invalid_response = {"headers": {"Link": None}, "body": "foo"}
    report_size_deltas.http_request = unittest.mock.MagicMock(return_value=invalid_response)

    # HTTP response body is not JSON
    with pytest.raises(expected_exception=json.decoder.JSONDecodeError):
        report_size_deltas.get_json_response(url=url)

    response = {"headers": {"Link": None}, "body": "[]"}
    report_size_deltas.http_request = unittest.mock.MagicMock(return_value=response)

    # Empty body
    response_data = report_size_deltas.get_json_response(url=url)
    assert json.loads(response["body"]) == response_data["json_data"]
    assert not response_data["additional_pages"]
    assert 0 == response_data["page_count"]
    report_size_deltas.http_request.assert_called_once_with(url=url)

    response = {"headers": {"Link": None}, "body": "[42]"}
    report_size_deltas.http_request = unittest.mock.MagicMock(return_value=response)

    # Non-empty body, Link field is None
    response_data = report_size_deltas.get_json_response(url=url)
    assert json.loads(response["body"]) == response_data["json_data"]
    assert not response_data["additional_pages"]
    assert 1 == response_data["page_count"]

    response = {
        "headers": {
            "Link": '<https://api.github.com/repositories/919161/pulls?page=2>; rel="next", '
            '"<https://api.github.com/repositories/919161/pulls?page=4>; rel="last"'
        },
        "body": "[42]",
    }
    report_size_deltas.http_request = unittest.mock.MagicMock(return_value=response)

    # Non-empty body, Link field is populated
    response_data = report_size_deltas.get_json_response(url=url)
    assert json.loads(response["body"]) == response_data["json_data"]
    assert response_data["additional_pages"]
    assert 4 == response_data["page_count"]

    report_size_deltas.http_request = unittest.mock.MagicMock(side_effect=Exception())

    # HTTP response body is not JSON
    with pytest.raises(expected_exception=Exception):
        report_size_deltas.get_json_response(url=url)


def test_http_request():
    url = "test_url"
    data = "test_data"

    report_size_deltas = get_reportsizedeltas_object()

    report_size_deltas.raw_http_request = unittest.mock.MagicMock()

    report_size_deltas.http_request(url=url, data=data)

    report_size_deltas.raw_http_request.assert_called_once_with(url=url, data=data)


def test_raw_http_request(mocker):
    user_name = "test_user"
    token = "test_token"
    url = "https://api.github.com/repo/foo/bar"
    data = "test_data"

    class Request:
        def add_unredirected_header(self):
            pass  # pragma: no cover

    mocker.patch.object(Request, "add_unredirected_header")
    request = Request()
    urlopen_return = unittest.mock.sentinel.urlopen_return

    report_size_deltas = get_reportsizedeltas_object(repository_name=user_name + "/FooRepositoryName", token=token)

    mocker.patch.object(urllib.request, "Request", autospec=True, return_value=request)
    mocker.patch("reportsizedeltas.ReportSizeDeltas.handle_rate_limiting", autospec=True)
    mocker.patch.object(urllib.request, "urlopen", autospec=True, return_value=urlopen_return)

    report_size_deltas.raw_http_request(url=url, data=data)

    urllib.request.Request.assert_called_once_with(
        url=url,
        data=data,
    )
    request.add_unredirected_header.assert_has_calls(
        calls=[
            unittest.mock.call(key="Accept", val="application/vnd.github+json"),
            unittest.mock.call(key="Authorization", val="Bearer " + token),
            unittest.mock.call(key="User-Agent", val=user_name),
            unittest.mock.call(key="X-GitHub-Api-Version", val="2022-11-28"),
        ]
    )
    # URL is subject to GitHub API rate limiting
    report_size_deltas.handle_rate_limiting.assert_called_once()

    # URL is not subject to GitHub API rate limiting
    mocker.resetall()
    url = "https://api.github.com/rate_limit"
    assert report_size_deltas.raw_http_request(url=url, data=data) == urlopen_return
    report_size_deltas.handle_rate_limiting.assert_not_called()
    urllib.request.urlopen.assert_called_once_with(url=request)

    # urllib.request.urlopen() has non-recoverable exception
    urllib.request.urlopen.side_effect = urllib.error.HTTPError(
        url="http://example.com", code=404, msg="", hdrs=None, fp=None
    )
    mocker.patch("reportsizedeltas.determine_urlopen_retry", autospec=True, return_value=False)
    with pytest.raises(expected_exception=urllib.error.HTTPError):
        report_size_deltas.raw_http_request(url=url, data=data)

    # urllib.request.urlopen() has potentially recoverable exceptions, but exceeds retry count
    reportsizedeltas.determine_urlopen_retry.return_value = True
    with pytest.raises(expected_exception=urllib.error.HTTPError):
        report_size_deltas.raw_http_request(url=url, data=data)


def test_handle_rate_limiting():
    report_size_deltas = get_reportsizedeltas_object()

    json_data = {"json_data": {"resources": {"core": {"remaining": 0, "reset": 1234, "limit": 42}}}}
    report_size_deltas.get_json_response = unittest.mock.MagicMock(return_value=json_data)

    with pytest.raises(expected_exception=SystemExit, match="0"):
        report_size_deltas.handle_rate_limiting()

    report_size_deltas.get_json_response.assert_called_once_with(url="https://api.github.com/rate_limit")

    json_data["json_data"]["resources"]["core"]["remaining"] = 42
    report_size_deltas.handle_rate_limiting()


def test_determine_urlopen_retry_true(mocker):
    mocker.patch("time.sleep", autospec=True)

    assert reportsizedeltas.determine_urlopen_retry(
        exception=urllib.error.HTTPError(None, 502, "Bad Gateway", None, None)
    )


def test_determine_urlopen_retry_false():
    assert not reportsizedeltas.determine_urlopen_retry(
        exception=urllib.error.HTTPError(None, 401, "Unauthorized", None, None)
    )


def test_get_page_count():
    page_count = 4
    link_header = (
        '<https://api.github.com/repositories/919161/pulls?page=2>; rel="next", '
        '"<https://api.github.com/repositories/919161/pulls?page=' + str(page_count) + '>; rel="last"'
    )

    assert page_count == reportsizedeltas.get_page_count(link_header=link_header)


@pytest.mark.parametrize(
    "report, column_heading, expected_column_number, expected_report",
    [
        (
            [["Board", "foo memory type", "%"], ["foo board", 12, 234]],
            "foo memory type",
            1,
            [["Board", "foo memory type", "%"], ["foo board", 12, 234]],
        ),
        (
            [["Board", "foo memory type", "%"], ["foo board", 12, 234, "bar board"]],
            "bar memory type",
            3,
            [["Board", "foo memory type", "%", "bar memory type", "%"], ["foo board", 12, 234, "bar board", "", ""]],
        ),
    ],
)
def test_get_report_column_number(report, column_heading, expected_column_number, expected_report):
    assert (
        reportsizedeltas.get_report_column_number(report=report, column_heading=column_heading)
        == expected_column_number
    )
    assert report == expected_report


def test_generate_markdown_table():
    assert (
        reportsizedeltas.generate_markdown_table(row_list=[["Board", "Flash", "RAM"], ["foo:bar:baz", 42, 11]])
        == "Board|Flash|RAM\n-|-|-\nfoo:bar:baz|42|11\n"
    )


def test_generate_csv_table():
    assert reportsizedeltas.generate_csv_table(row_list=[["Board", "Flash", "RAM"], ["foo:bar:baz", 42, 11]]) == (
        "Board,Flash,RAM\nfoo:bar:baz,42,11\n"
    )
