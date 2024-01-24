import csv
import io
import json
import logging
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def main() -> None:
    set_verbosity(enable_verbosity=False)

    if "INPUT_SIZE-DELTAS-REPORTS-ARTIFACT-NAME" in os.environ:
        print(
            "::warning::The size-deltas-report-artifact-name input is deprecated. Use the equivalent input: "
            "sketches-reports-source instead."
        )
        os.environ["INPUT_SKETCHES-REPORTS-SOURCE"] = os.environ["INPUT_SIZE-DELTAS-REPORTS-ARTIFACT-NAME"]

    report_size_deltas = ReportSizeDeltas(
        repository_name=os.environ["GITHUB_REPOSITORY"],
        sketches_reports_source=os.environ["INPUT_SKETCHES-REPORTS-SOURCE"],
        token=os.environ["INPUT_GITHUB-TOKEN"],
    )

    report_size_deltas.report_size_deltas()


def set_verbosity(enable_verbosity: bool) -> None:
    """Turn debug output on or off.

    Keyword arguments:
    enable_verbosity -- enable/disable verbose output
                              (True, False)
    """
    # DEBUG: automatically generated output and all higher log level output
    # INFO: manually specified output and all higher log level output
    verbose_logging_level = logging.DEBUG

    if type(enable_verbosity) is not bool:
        raise TypeError
    if enable_verbosity:
        logger.setLevel(level=verbose_logging_level)
    else:
        logger.setLevel(level=logging.WARNING)


class ReportSizeDeltas:
    """Methods for creating and submitting the memory usage change reports.

    Keyword arguments:
    repository_name -- repository owner and name e.g., octocat/Hello-World
    artifact_name -- regular expression for the names of the workflow artifacts that contain the memory usage data
    token -- GitHub access token
    """

    report_key_beginning = "**Memory usage change @ "
    not_applicable_indicator = "N/A"

    class ReportKeys:
        """Key names used in the sketches report dictionary."""

        boards = "boards"
        board = "board"
        commit_hash = "commit_hash"
        commit_url = "commit_url"
        sizes = "sizes"
        name = "name"
        absolute = "absolute"
        relative = "relative"
        current = "current"
        previous = "previous"
        delta = "delta"
        minimum = "minimum"
        maximum = "maximum"
        sketches = "sketches"
        compilation_success = "compilation_success"

    def __init__(self, repository_name: str, sketches_reports_source: str, token: str) -> None:
        self.repository_name = repository_name
        self.sketches_reports_source = sketches_reports_source
        self.token = token

    def report_size_deltas(self) -> None:
        """Comment a report of memory usage change to pull request(s)."""
        if os.environ["GITHUB_EVENT_NAME"] == "pull_request":
            # The sketches reports will be in a local folder location specified by the user
            self.report_size_deltas_from_local_reports()
        else:
            # The script is being run from a workflow triggered by something other than a PR
            # Scan the repository's pull requests and comment memory usage change reports where appropriate.
            self.report_size_deltas_from_workflow_artifacts()

    def report_size_deltas_from_local_reports(self) -> None:
        """Comment a report of memory usage change to the pull request."""
        sketches_reports_folder = pathlib.Path(os.environ["GITHUB_WORKSPACE"], self.sketches_reports_source)
        sketches_reports = self.get_sketches_reports(artifacts_folder_object=sketches_reports_folder)

        if sketches_reports:
            report = self.generate_report(sketches_reports=sketches_reports)

            with open(file=os.environ["GITHUB_EVENT_PATH"]) as github_event_file:
                pr_number = json.load(github_event_file)["pull_request"]["number"]

            self.comment_report(pr_number=pr_number, report_markdown=report)

    def report_size_deltas_from_workflow_artifacts(self) -> None:
        """Scan the repository's pull requests and comment memory usage change reports where appropriate."""
        # Get the repository's pull requests
        logger.debug("Getting PRs for " + self.repository_name)
        page_number = 1
        page_count = 1
        while page_number <= page_count:
            api_data = self.api_request(request="repos/" + self.repository_name + "/pulls", page_number=page_number)
            prs_data = api_data["json_data"]
            for pr_data in prs_data:
                # Note: closed PRs are not listed in the API response
                pr_number = pr_data["number"]
                pr_head_sha = pr_data["head"]["sha"]
                print("::debug::Processing pull request number:", pr_number)
                # When a PR is locked, only collaborators may comment. The automatically generated GITHUB_TOKEN owned by
                # the github-actions bot will likely be used. The bot doesn't have collaborator status so it will
                # generally be impossible to make reports on locked PRs.
                if pr_data["locked"]:
                    print("::debug::PR locked, skipping")
                    continue

                if self.report_exists(pr_number=pr_number, pr_head_sha=pr_head_sha):
                    # Go on to the next PR
                    print("::debug::Report already exists")
                    continue

                artifacts_data = self.get_artifacts_data_for_sha(
                    pr_user_login=pr_data["user"]["login"], pr_head_ref=pr_data["head"]["ref"], pr_head_sha=pr_head_sha
                )
                if artifacts_data is None:
                    # Go on to the next PR
                    print("::debug::No sketches report artifact found")
                    continue

                artifact_folder_object = self.get_artifacts(artifacts_data=artifacts_data)

                sketches_reports = self.get_sketches_reports(artifacts_folder_object=artifact_folder_object)

                if sketches_reports:
                    if sketches_reports[0][self.ReportKeys.commit_hash] != pr_head_sha:
                        # The deltas report key uses the hash from the report, but the report_exists() comparison is
                        # done using the hash provided by the API. If for some reason the two didn't match, it would
                        # result in the deltas report being done over and over again.
                        print("::warning::Report commit hash doesn't match PR's head commit hash, skipping")
                        continue

                    report = self.generate_report(sketches_reports=sketches_reports)

                    self.comment_report(pr_number=pr_number, report_markdown=report)

            page_number += 1
            page_count = api_data["page_count"]

    def report_exists(self, pr_number: int, pr_head_sha: str) -> bool:
        """Return whether a report has already been commented to the pull request thread for the latest workflow run.

        Keyword arguments:
        pr_number -- number of the pull request to check
        pr_head_sha -- PR's head branch hash
        """
        # Get the pull request's comments
        page_number = 1
        page_count = 1
        while page_number <= page_count:
            api_data = self.api_request(
                request="repos/" + self.repository_name + "/issues/" + str(pr_number) + "/comments",
                page_number=page_number,
            )

            comments_data = api_data["json_data"]
            for comment_data in comments_data:
                # Check if the comment is a report for the PR's head SHA
                if comment_data["body"].startswith(self.report_key_beginning + pr_head_sha):
                    return True

            page_number += 1
            page_count = api_data["page_count"]

        # No reports found for the PR's head SHA
        return False

    def get_artifacts_data_for_sha(self, pr_user_login: str, pr_head_ref: str, pr_head_sha: str):
        """Return the list of data objects for the report artifacts associated with the given head commit hash.

        Keyword arguments:
        pr_user_login -- user name of the PR author (used to reduce number of GitHub API requests)
        pr_head_ref -- name of the PR head branch (used to reduce number of GitHub API requests)
        pr_head_sha -- hash of the head commit in the PR branch
        """
        # Get the repository's workflow runs
        page_number = 1
        page_count = 1
        while page_number <= page_count:
            api_data = self.api_request(
                request="repos/" + self.repository_name + "/actions/runs",
                request_parameters="actor="
                + pr_user_login
                + "&branch="
                + pr_head_ref
                + "&event=pull_request&status=completed",
                page_number=page_number,
            )
            runs_data = api_data["json_data"]

            # Find the runs with the head SHA of the PR (there may be multiple runs)
            for run_data in runs_data["workflow_runs"]:
                if run_data["head_sha"] == pr_head_sha:
                    # Check if this run has the artifacts we're looking for
                    artifacts_data = self.get_artifacts_data_for_run(run_id=run_data["id"])
                    if artifacts_data is not None:
                        return artifacts_data

            page_number += 1
            page_count = api_data["page_count"]

        # No matching artifact found
        return None

    def get_artifacts_data_for_run(self, run_id: str):
        """Return the list of data objects for the artifacts associated with the given GitHub Actions workflow run.

        Keyword arguments:
        run_id -- GitHub Actions workflow run ID
        """
        report_artifacts_data = []

        # Get the workflow run's artifacts
        page_number = 1
        page_count = 1
        while page_number <= page_count:
            api_data = self.api_request(
                request="repos/" + self.repository_name + "/actions/runs/" + str(run_id) + "/artifacts",
                page_number=page_number,
            )
            artifacts_data = api_data["json_data"]

            for artifact_data in artifacts_data["artifacts"]:
                # The artifacts are identified by name matching a pattern
                if not artifact_data["expired"] and re.match(
                    pattern=self.sketches_reports_source, string=artifact_data["name"]
                ):
                    print("::debug::Found report artifact:", artifact_data["name"])
                    report_artifacts_data.append(artifact_data)

            page_number += 1
            page_count = api_data["page_count"]

        if len(report_artifacts_data) > 0:
            return report_artifacts_data
        else:
            # No matching artifact found
            return None

    def get_artifacts(self, artifacts_data):
        """Download and unzip the artifacts and return an object for the temporary directory containing them.

        Keyword arguments:
        artifact_data -- data object for the artifact
        """
        # Create temporary folder
        artifacts_folder_object = tempfile.TemporaryDirectory(prefix="reportsizedeltas-")
        artifacts_folder_path = pathlib.Path(artifacts_folder_object.name)
        for artifact_data in artifacts_data:
            try:
                print("::debug::Downloading artifact:", artifact_data["name"])
                artifact_folder_path = artifacts_folder_path.joinpath(artifact_data["name"])
                artifact_folder_path.mkdir()
                artifact_zip_file_path = artifact_folder_path.joinpath(artifact_data["name"] + ".zip")
                # Download artifact
                with artifact_zip_file_path.open(mode="wb") as out_file:
                    with self.raw_http_request(url=artifact_data["archive_download_url"]) as fp:
                        out_file.write(fp.read())

                # Unzip artifact
                with zipfile.ZipFile(file=artifact_zip_file_path, mode="r") as zip_ref:
                    zip_ref.extractall(path=artifact_folder_path)
                artifact_zip_file_path.unlink()

            except Exception:
                artifacts_folder_object.cleanup()
                raise

        return artifacts_folder_object

    def get_sketches_reports(self, artifacts_folder_object):
        """Parse the artifact files and return a list containing the data.

        Keyword arguments:
        artifacts_folder_object -- object containing the data about the temporary folder that stores the Markdown files
        """
        with artifacts_folder_object as artifacts_folder:
            # artifact_folder will be a string when running in non-local report mode
            artifacts_folder = pathlib.Path(artifacts_folder)
            sketches_reports = []
            for report_filename in sorted(artifacts_folder.rglob(pattern="*.json")):
                if report_filename.is_dir():
                    # pathlib.Path.rglob returns matching folders in addition to files
                    continue

                # Combine sketches reports into an array
                with open(file=report_filename) as report_file:
                    report_data = json.load(report_file)
                    if (
                        (self.ReportKeys.boards not in report_data)
                        or (self.ReportKeys.sizes not in report_data[self.ReportKeys.boards][0])
                        or (
                            self.ReportKeys.maximum
                            not in report_data[self.ReportKeys.boards][0][self.ReportKeys.sizes][0]
                        )
                    ):
                        # Sketches reports use an old format, skip
                        print("Old format sketches report found, skipping")
                        continue

                    for fqbn_data in report_data[self.ReportKeys.boards]:
                        if self.ReportKeys.sizes in fqbn_data:
                            # The report contains deltas data
                            sketches_reports.append(report_data)
                            break

        if not sketches_reports:
            print(
                "No size deltas data found in workflow artifact for this PR. The compile-examples action's "
                "enable-size-deltas-report input must be set to true to produce size deltas data."
            )

        return sketches_reports

    def generate_report(self, sketches_reports) -> str:
        """Return the Markdown for the deltas report comment.

        Keyword arguments:
        sketches_reports -- list of sketches reports containing the data to generate the deltas report from
        """
        # From https://github.community/t/maximum-length-for-the-comment-body-in-issues-and-pr/148867/2
        # > PR body/Issue comments are still stored in MySQL as a mediumblob with a maximum value length of 262,144.
        # > This equals a limit of 65,536 4-byte unicode characters.
        maximum_report_length = 262144

        fqbn_column_heading = "Board"

        # Generate summary report data
        summary_report_data = [[fqbn_column_heading]]
        for fqbns_data in sketches_reports:
            for fqbn_data in fqbns_data[self.ReportKeys.boards]:
                self.add_summary_report_row(summary_report_data, fqbn_data)

        # Generate detailed report data
        full_report_data = [[fqbn_column_heading]]
        for fqbns_data in sketches_reports:
            for fqbn_data in fqbns_data[self.ReportKeys.boards]:
                self.add_detailed_report_row(full_report_data, fqbn_data)

        # Add comment heading
        report_markdown = self.report_key_beginning + sketches_reports[0][self.ReportKeys.commit_hash] + "**\n\n"

        # Add summary table
        report_markdown = report_markdown + generate_markdown_table(row_list=summary_report_data) + "\n"

        # Add full table
        report_markdown_with_table = (
            report_markdown + "<details>\n" "<summary>Click for full report table</summary>\n\n"
        )
        report_markdown_with_table = (
            report_markdown_with_table + generate_markdown_table(row_list=full_report_data) + "\n</details>\n\n"
        )

        if len(report_markdown_with_table) < maximum_report_length:
            report_markdown = report_markdown_with_table

            # Add full CSV
            report_markdown_with_csv = (
                report_markdown + "<details>\n" "<summary>Click for full report CSV</summary>\n\n" "```\n"
            )
            report_markdown_with_csv = (
                report_markdown_with_csv + generate_csv_table(row_list=full_report_data) + "```\n</details>"
            )

            if len(report_markdown_with_csv) < maximum_report_length:
                report_markdown = report_markdown_with_csv

        logger.debug("Report:\n" + report_markdown)
        return report_markdown

    def add_summary_report_row(self, report_data, fqbn_data) -> None:
        """Add a row to the summary report.

        Keyword arguments:
        report_data -- the report to add the row to
        right_directory -- the data used to populate the row
        """
        row_number = len(report_data)
        # Add a row to the report
        row = ["" for _ in range(len(report_data[0]))]
        row[0] = f"`{fqbn_data[self.ReportKeys.board]}`"
        report_data.append(row)

        # Populate the row with data
        for size_data in fqbn_data[self.ReportKeys.sizes]:
            # Determine column number for this memory type
            column_number = get_report_column_number(report=report_data, column_heading=size_data[self.ReportKeys.name])

            # Add the memory data to the cell
            if self.ReportKeys.delta in size_data:
                # Absolute data
                report_data[row_number][column_number] = self.get_summary_value(
                    show_emoji=True,
                    minimum=size_data[self.ReportKeys.delta][self.ReportKeys.absolute][self.ReportKeys.minimum],
                    maximum=size_data[self.ReportKeys.delta][self.ReportKeys.absolute][self.ReportKeys.maximum],
                )

                # Relative data
                report_data[row_number][column_number + 1] = self.get_summary_value(
                    show_emoji=False,
                    minimum=size_data[self.ReportKeys.delta][self.ReportKeys.relative][self.ReportKeys.minimum],
                    maximum=size_data[self.ReportKeys.delta][self.ReportKeys.relative][self.ReportKeys.maximum],
                )
            else:
                # Absolute data
                report_data[row_number][column_number] = self.get_summary_value(
                    show_emoji=True, minimum=self.not_applicable_indicator, maximum=self.not_applicable_indicator
                )

                # Relative data
                report_data[row_number][column_number + 1] = self.get_summary_value(
                    show_emoji=False, minimum=self.not_applicable_indicator, maximum=self.not_applicable_indicator
                )

    def add_detailed_report_row(self, report_data, fqbn_data) -> None:
        """Add a row to the detailed report.

        Keyword arguments:
        report_data -- the report to add the row to
        right_directory -- the data used to populate the row
        """
        row_number = len(report_data)
        # Add a row to the report
        row = ["" for _ in range(len(report_data[0]))]
        row[0] = f"`{fqbn_data[self.ReportKeys.board]}`"
        report_data.append(row)

        # Populate the row with data
        for sketch in fqbn_data[self.ReportKeys.sketches]:
            for size_data in sketch[self.ReportKeys.sizes]:
                # Determine column number for this memory type
                column_number = get_report_column_number(
                    report=report_data,
                    column_heading=(
                        "`{sketch_name}`<br>{size_name}".format(
                            sketch_name=sketch[self.ReportKeys.name], size_name=size_data[self.ReportKeys.name]
                        )
                    ),
                )

                # Add the memory data to the cell
                if self.ReportKeys.delta in size_data:
                    # Absolute
                    report_data[row_number][column_number] = size_data[self.ReportKeys.delta][self.ReportKeys.absolute]

                    # Relative
                    report_data[row_number][column_number + 1] = size_data[self.ReportKeys.delta][
                        self.ReportKeys.relative
                    ]
                else:
                    # Absolute
                    report_data[row_number][column_number] = self.not_applicable_indicator

                    # Relative
                    report_data[row_number][column_number + 1] = self.not_applicable_indicator

    def get_summary_value(self, show_emoji: bool, minimum, maximum) -> str:
        """Return the Markdown formatted text for a memory change data cell in the report table.

        Keyword arguments:
        show_emoji -- whether to add the emoji change indicator
        minimum -- minimum amount of change for this memory type
        maximum -- maximum amount of change for this memory type
        """
        size_decrease_emoji = ":green_heart:"
        size_ambiguous_emoji = ":grey_question:"
        size_increase_emoji = ":small_red_triangle:"

        value = None
        if minimum == self.not_applicable_indicator:
            value = self.not_applicable_indicator
            emoji = None
        elif minimum < 0 and maximum <= 0:
            emoji = size_decrease_emoji
        elif minimum == 0 and maximum == 0:
            emoji = None
        elif minimum >= 0 and maximum > 0:
            emoji = size_increase_emoji
        else:
            emoji = size_ambiguous_emoji

        if value is None:
            # Prepend + to positive values to improve readability
            if minimum > 0:
                minimum = "+" + str(minimum)
            if maximum > 0:
                maximum = "+" + str(maximum)

            value = str(minimum) + " - " + str(maximum)

        if show_emoji and (emoji is not None):
            value = emoji + " " + value

        return value

    def comment_report(self, pr_number: int, report_markdown: str) -> None:
        """Submit the report as a comment on the PR thread.

        Keyword arguments:
        pr_number -- pull request number to submit the report to
        report_markdown -- Markdown formatted report
        """
        print("::debug::Adding deltas report comment to pull request")
        report_data = json.dumps(obj={"body": report_markdown}).encode(encoding="utf-8")
        url = "https://api.github.com/repos/" + self.repository_name + "/issues/" + str(pr_number) + "/comments"

        self.http_request(url=url, data=report_data)

    def api_request(self, request: str, request_parameters: str = "", page_number: int = 1):
        """Do a GitHub API request. Return a dictionary containing:
        json_data -- JSON object containing the response
        additional_pages -- indicates whether more pages of results remain (True, False)
        page_count -- total number of pages of results

        Keyword arguments:
        request -- the section of the URL following https://api.github.com/
        request_parameters -- GitHub API request parameters (see: https://developer.github.com/v3/#parameters)
                              (default value: "")
        page_number -- Some responses will be paginated. This argument specifies which page should be returned.
                       (default value: 1)
        """
        return self.get_json_response(
            url="https://api.github.com/"
            + request
            + "?"
            + request_parameters
            + "&page="
            + str(page_number)
            + "&per_page=100"
        )

    def get_json_response(self, url: str):
        """Load the specified URL and return a dictionary:
        json_data -- JSON object containing the response
        additional_pages -- indicates whether more pages of results remain (True, False)
        page_count -- total number of pages of results

        Keyword arguments:
        url -- the URL to load
        """
        try:
            response_data = self.http_request(url=url)
            try:
                json_data = json.loads(response_data["body"])
            except json.decoder.JSONDecodeError as exception:
                # Output some information on the exception
                logger.warning(str(exception.__class__.__name__) + ": " + str(exception))
                # Pass the exception on to the caller
                raise exception

            if not json_data:
                # There was no HTTP error but an empty list was returned (e.g. pulls API request when the repo
                # has no open PRs)
                page_count = 0
                additional_pages = False
            else:
                page_count = get_page_count(link_header=response_data["headers"]["Link"])
                if page_count > 1:
                    additional_pages = True
                else:
                    additional_pages = False

            return {"json_data": json_data, "additional_pages": additional_pages, "page_count": page_count}
        except Exception as exception:
            raise exception

    def http_request(self, url: str, data: bytes | None = None):
        """Make a request and return a dictionary:
        read -- the response
        info -- headers
        url -- the URL of the resource retrieved

        Keyword arguments:
        url -- the URL to load
        data -- data to pass with the request
                (default value: None)
        """
        with self.raw_http_request(url=url, data=data) as response_object:
            return {
                "body": response_object.read().decode(encoding="utf-8", errors="ignore"),
                "headers": response_object.info(),
                "url": response_object.geturl(),
            }

    def raw_http_request(self, url: str, data: bytes | None = None):
        """Make a request and return an object containing the response.

        Keyword arguments:
        url -- the URL to load
        data -- data to pass with the request
                (default value: None)
        """
        # Maximum times to retry opening the URL before giving up
        maximum_urlopen_retries = 3

        logger.info("Opening URL: " + url)

        request = urllib.request.Request(url=url, data=data)
        request.add_unredirected_header(key="Accept", val="application/vnd.github+json")
        request.add_unredirected_header(key="Authorization", val="Bearer " + self.token)
        request.add_unredirected_header(key="User-Agent", val=self.repository_name.split("/")[0])
        request.add_unredirected_header(key="X-GitHub-Api-Version", val="2022-11-28")

        retry_count = 0
        while True:
            try:
                # The rate limit API is not subject to rate limiting
                if url.startswith("https://api.github.com") and not url.startswith("https://api.github.com/rate_limit"):
                    self.handle_rate_limiting()
                return urllib.request.urlopen(url=request)
            except urllib.error.HTTPError as exception:
                if determine_urlopen_retry(exception=exception):
                    if retry_count < maximum_urlopen_retries:
                        retry_count += 1
                        continue
                    else:
                        # Maximum retries reached without successfully opening URL
                        print("Maximum number of URL load retries exceeded")

                print(f"::error::{exception.__class__.__name__}: {exception}")
                for line in exception.fp:
                    print(line.decode(encoding="utf-8", errors="ignore"))

                raise exception

    def handle_rate_limiting(self) -> None:
        """Check whether the GitHub API request limit has been reached.
        If so, exit with exit status 0.
        """
        rate_limiting_data = self.get_json_response(url="https://api.github.com/rate_limit")["json_data"]
        # GitHub has two API types, each with their own request limits and counters.
        # "search" applies only to api.github.com/search.
        # "core" applies to all other parts of the API.
        # Since this code only uses the "core" API, only those values are relevant
        logger.debug("GitHub core API request allotment: " + str(rate_limiting_data["resources"]["core"]["limit"]))
        logger.debug("Remaining API requests: " + str(rate_limiting_data["resources"]["core"]["remaining"]))
        logger.debug("API request count reset time: " + str(rate_limiting_data["resources"]["core"]["reset"]))

        if rate_limiting_data["resources"]["core"]["remaining"] == 0:
            # GitHub uses a fixed rate limit window of 60 minutes. The window starts when the API request count goes
            # from 0 to 1. 60 minutes after the start of the window, the request count is reset to 0.
            print("::warning::GitHub API request quota has been reached. Giving up for now.")
            sys.exit(0)


def determine_urlopen_retry(exception: urllib.error.HTTPError) -> bool:
    """Determine whether the exception warrants another attempt at opening the URL.
    If so, delay then return True. Otherwise, return False.

    Keyword arguments:
    exception -- the exception
    """
    # Retry urlopen after exceptions that start with the following strings
    urlopen_retry_exceptions = [
        # urllib.error.HTTPError: HTTP Error 403: Forbidden
        "HTTPError: HTTP Error 403",
        # urllib.error.HTTPError: HTTP Error 502: Bad Gateway
        "HTTPError: HTTP Error 502",
        # urllib.error.HTTPError: HTTP Error 503: Service Unavailable
        # caused by rate limiting
        "HTTPError: HTTP Error 503",
        # http.client.RemoteDisconnected: Remote end closed connection without response
        "RemoteDisconnected",
        # ConnectionResetError: [Errno 104] Connection reset by peer
        "ConnectionResetError",
        # ConnectionRefusedError: [WinError 10061] No connection could be made because the target machine actively
        # refused it
        "ConnectionRefusedError",
        # urllib.error.URLError: <urlopen error [WinError 10061] No connection could be made because the target
        # machine actively refused it>
        "<urlopen error [WinError 10061] No connection could be made because the target machine actively refused "
        "it>",
    ]

    # Delay before retry (seconds)
    urlopen_retry_delay = 30

    exception_string = str(exception.__class__.__name__) + ": " + str(exception)
    logger.info(exception_string)
    for urlopen_retry_exception in urlopen_retry_exceptions:
        if str(exception_string).startswith(urlopen_retry_exception):
            # These errors may only be temporary, retry
            logger.warning("Temporarily unable to open URL (" + str(exception) + "), retrying")
            time.sleep(urlopen_retry_delay)
            return True

    # Other errors are probably permanent so give up
    if str(exception_string).startswith("HTTPError: HTTP Error 401"):
        # Give a nice hint as to the cause of this error
        print("::error::HTTP Error 401 may be caused by providing an incorrect GitHub personal access token.")
    return False


def get_page_count(link_header: str | None) -> int:
    """Return the number of pages of the API response.

    Keyword arguments:
    link_header -- Link header of the HTTP response
    """
    page_count = 1
    if link_header is not None:
        # Get the pagination data
        for link in link_header.split(","):
            if link[-13:] == '>; rel="last"':
                for parameter in re.split("[?&>]", link):
                    if parameter[:5] == "page=":
                        page_count = int(parameter.split("=")[1])
                        break
                break
    return page_count


def get_report_column_number(report, column_heading: str) -> int:
    """Return the column number of the given heading.

    Keyword arguments:
    column_heading -- the text of the column heading. If it doesn't exist, a column will be created with this heading.
    """
    relative_column_heading = "%"

    try:
        column_number = report[0].index(column_heading, 1)
    except ValueError:
        # There is no existing column, so create columns for relative and absolute
        column_number = len(report[0])

        # Absolute column
        # Add the heading
        report[0].append(column_heading)
        # Expand the size of the final row (the current row) to match the new number of columns
        report[len(report) - 1].append("")

        # Relative column
        # Add the heading
        report[0].append(relative_column_heading)
        # Expand the size of the final row (the current row) to match the new number of columns
        report[len(report) - 1].append("")

    return column_number


def generate_markdown_table(row_list) -> str:
    """Return the data formatted as a Markdown table.

    Keyword arguments:
    row_list -- list containing the data
    """
    # Generate heading row
    markdown_table = "|".join([str(cell) for cell in row_list[0]]) + "\n"
    # Add divider row
    markdown_table = markdown_table + "|".join(["-" for _ in row_list[0]]) + "\n"
    # Add data rows
    for row in row_list[1:]:
        markdown_table = markdown_table + "|".join([str(cell) for cell in row]) + "\n"

    return markdown_table


def generate_csv_table(row_list) -> str:
    """Return a string containing the supplied data formatted as CSV.

    Keyword arguments:
    row_list -- list containing the data
    """
    csv_string = io.StringIO()
    csv_writer = csv.writer(csv_string, lineterminator="\n")
    for row in row_list:
        cleaned_row = []
        for cell in row:
            cleaned_cell = cell
            if isinstance(cleaned_cell, str):
                # The "code span" markup is not needed in the CSV report.
                cleaned_cell = cleaned_cell.replace("`", "")

            cleaned_row.append(cleaned_cell)

        csv_writer.writerow(cleaned_row)

    return csv_string.getvalue()


# Only execute the following code if the script is run directly, not imported
if __name__ == "__main__":
    main()  # pragma: no cover
