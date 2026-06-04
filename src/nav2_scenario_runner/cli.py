from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .compare import (
    compare_report_files,
    format_compare_markdown,
    parse_metric_rule,
    write_compare_markdown,
    write_compare_report,
)
from .doctor import run_doctor, write_doctor_report
from .evaluate import (
    MetricDirections,
    build_evaluation,
    format_evaluation_html,
    format_evaluation_markdown,
    load_entries,
    parse_entry,
)
from .execution import BackendUnavailable
from .history import (
    append_history,
    build_trend,
    format_trend_html,
    format_trend_markdown,
    load_history,
    summarize_report,
    trend_to_dict,
)
from .init_project import InitError, available_templates, init_project
from .report_view import (
    append_text_report,
    format_run_report,
    load_run_report,
    report_has_failures,
    write_text_report,
)
from .replay import format_replay_html, load_map, load_replay_scenarios
from .reporting import write_json_report, write_junit_report, write_trace_report
from .runner import dry_run, run_with_backend_factory
from .scenario import discover_scenarios, load_scenario
from .schema import SchemaValidator, default_schema_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nav2_scenario_runner",
        description="Scenario-as-Code test runner for Nav2.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a starter scenario suite.")
    init_parser.add_argument("target_dir", nargs="?", type=Path, default=Path("."), help="Directory to initialize.")
    init_parser.add_argument(
        "--template",
        choices=available_templates(),
        default="turtlebot3-gazebo",
        help="Starter template to generate.",
    )
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing generated files.")

    doctor_parser = subparsers.add_parser("doctor", help="Check local runtime environment.")
    doctor_parser.add_argument(
        "--check-ros",
        action="store_true",
        help="Require ROS 2/Nav2 Python modules instead of reporting them as optional warnings.",
    )
    doctor_parser.add_argument(
        "--check-gazebo",
        action="store_true",
        help="Require Gazebo Sim CLI and ros_gz_bridge preflight checks.",
    )
    doctor_parser.add_argument(
        "--check-ros-graph",
        action="store_true",
        help="Require ROS graph CLI checks using ros2 node/topic list.",
    )
    doctor_parser.add_argument("--json", type=Path, default=None, help="Optional JSON doctor report path.")

    lint_parser = subparsers.add_parser("lint", help="Validate scenario YAML files.")
    lint_parser.add_argument("paths", nargs="+", help="Scenario files or directories.")
    lint_parser.add_argument("--schema", type=Path, default=None, help="Override JSON Schema path.")

    list_parser = subparsers.add_parser("list", help="List discovered scenarios.")
    list_parser.add_argument("paths", nargs="+", help="Scenario files or directories.")
    list_parser.add_argument("--tag", action="append", default=[], help="Only include scenarios with this tag. Can be repeated.")
    list_parser.add_argument("--schema", type=Path, default=None, help="Override JSON Schema path.")

    run_parser = subparsers.add_parser("run", help="Validate and run scenarios.")
    run_parser.add_argument("paths", nargs="+", help="Scenario files or directories.")
    run_parser.add_argument("--tag", action="append", default=[], help="Only run scenarios with this tag. Can be repeated.")
    run_parser.add_argument("--schema", type=Path, default=None, help="Override JSON Schema path.")
    run_parser.add_argument("--dry-run", action="store_true", help="Validate and plan scenarios without ROS/Nav2 execution.")
    run_parser.add_argument(
        "--mode",
        choices=["attach", "dry-run", "gazebo-sim"],
        default="attach",
        help="Execution mode. attach connects to ROS; gazebo-sim runs a simulator lifecycle smoke.",
    )
    run_parser.add_argument(
        "--sim-startup-timeout",
        type=float,
        default=5.0,
        help="Seconds to keep simulator lifecycle smoke processes alive before declaring startup successful.",
    )
    run_parser.add_argument(
        "--skip-gazebo-preflight",
        action="store_true",
        help="Skip doctor --check-gazebo before --mode gazebo-sim. Intended for prevalidated CI images.",
    )
    run_parser.add_argument(
        "--wait-for-clock",
        action="store_true",
        help="In --mode gazebo-sim, wait for one /clock message after simulator startup.",
    )
    run_parser.add_argument(
        "--clock-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for /clock when --wait-for-clock is set.",
    )
    run_parser.add_argument(
        "--execute-nav2",
        action="store_true",
        help="In --mode gazebo-sim, execute scenario Nav2 steps against the active ROS graph.",
    )
    run_parser.add_argument(
        "--launch-scenario-stack",
        action="store_true",
        help="In --mode gazebo-sim, launch simulator.launch and nav2.bringup blocks with ros2 launch.",
    )
    run_parser.add_argument(
        "--wait-for-ros-graph",
        action="store_true",
        help="In --mode gazebo-sim, wait until ros2 node/topic list can inspect the ROS graph.",
    )
    run_parser.add_argument(
        "--ros-graph-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for ROS graph readiness when --wait-for-ros-graph is set.",
    )
    run_parser.add_argument(
        "--wait-for-nav2",
        action="store_true",
        help="In --mode gazebo-sim, wait for the Nav2 NavigateToPose action server before executing steps.",
    )
    run_parser.add_argument(
        "--nav2-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for Nav2 readiness when --wait-for-nav2 is set.",
    )
    run_parser.add_argument(
        "--wait-for-navigation-data",
        action="store_true",
        help="In --mode gazebo-sim, wait for TF, map, and costmap topics before executing steps.",
    )
    run_parser.add_argument(
        "--navigation-data-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for navigation data readiness when --wait-for-navigation-data is set.",
    )
    run_parser.add_argument(
        "--reset-world",
        action="store_true",
        help="In --mode gazebo-sim, reset the Gazebo world after simulator startup.",
    )
    run_parser.add_argument(
        "--world-reset-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for Gazebo world reset when --reset-world is set.",
    )
    run_parser.add_argument(
        "--execute-simulator-steps",
        action="store_true",
        help="In --mode gazebo-sim, execute top-level simulator steps such as spawn_obstacle and move_entity.",
    )
    run_parser.add_argument(
        "--simulator-step-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for each Gazebo simulator step service call.",
    )
    run_parser.add_argument(
        "--collect-contacts",
        action="store_true",
        help="In --mode gazebo-sim, collect Gazebo contact topics and emit collision metrics.",
    )
    run_parser.add_argument(
        "--contact-topic",
        action="append",
        default=[],
        help="Gazebo contact topic to monitor. Can be repeated. Defaults to contact topic discovery.",
    )
    run_parser.add_argument(
        "--contact-discovery-timeout",
        type=float,
        default=5.0,
        help="Seconds to wait for gz topic discovery when --collect-contacts is set without --contact-topic.",
    )
    run_parser.add_argument("--report-dir", type=Path, default=Path("reports"), help="Directory for generated reports.")
    run_parser.add_argument("--json-report", default="results.json", help="JSON report filename under --report-dir.")
    run_parser.add_argument("--junit-report", default="junit.xml", help="JUnit XML report filename under --report-dir.")
    run_parser.add_argument("--trace-report", default=None, help="Optional trace JSON filename under --report-dir.")
    run_parser.add_argument("--markdown-report", default=None, help="Optional Markdown summary filename under --report-dir.")
    run_parser.add_argument("--html-report", default=None, help="Optional HTML summary filename under --report-dir.")
    run_parser.add_argument(
        "--github-summary",
        action="store_true",
        help="Append a Markdown summary to the GITHUB_STEP_SUMMARY file after running scenarios.",
    )

    report_parser = subparsers.add_parser("report", help="Render a JSON run report as a human-readable summary.")
    report_parser.add_argument("path", type=Path, help="JSON run report path.")
    report_parser.add_argument(
        "--format",
        choices=["console", "markdown", "html"],
        default="console",
        help="Summary output format.",
    )
    report_parser.add_argument("--output", type=Path, default=None, help="Optional summary output path.")
    report_parser.add_argument(
        "--github-summary",
        action="store_true",
        help="Append a Markdown summary to the GITHUB_STEP_SUMMARY file.",
    )
    report_parser.add_argument(
        "--fail-on-failure",
        action="store_true",
        help="Return non-zero if the report contains failed scenarios.",
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Rank multiple Nav2 configurations across a scenario suite into a leaderboard dashboard.",
    )
    evaluate_parser.add_argument(
        "--entry",
        action="append",
        default=[],
        metavar="LABEL=REPORT.json",
        required=True,
        help="A named configuration and its JSON run report. Repeat for each configuration (min 2).",
    )
    evaluate_parser.add_argument(
        "--lower-is-better",
        action="append",
        default=[],
        metavar="METRIC",
        help="Treat this metric as better when smaller, overriding defaults. Can be repeated.",
    )
    evaluate_parser.add_argument(
        "--higher-is-better",
        action="append",
        default=[],
        metavar="METRIC",
        help="Treat this metric as better when larger, overriding defaults. Can be repeated.",
    )
    evaluate_parser.add_argument("--html-output", type=Path, default=None, help="Optional HTML dashboard path.")
    evaluate_parser.add_argument("--markdown-output", type=Path, default=None, help="Optional Markdown summary path.")
    evaluate_parser.add_argument("--json-output", type=Path, default=None, help="Optional machine-readable leaderboard JSON path.")
    evaluate_parser.add_argument(
        "--github-summary",
        action="store_true",
        help="Append the Markdown leaderboard to the GITHUB_STEP_SUMMARY file.",
    )

    replay_parser = subparsers.add_parser(
        "replay",
        help="Render an animated trajectory replay from a run report, optionally over a ROS map.",
    )
    replay_parser.add_argument("report", type=Path, help="JSON run report path.")
    replay_parser.add_argument("--html-output", type=Path, required=True, help="HTML replay output path.")
    replay_parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Only replay this scenario id. Can be repeated. Defaults to all with trajectories.",
    )
    replay_parser.add_argument(
        "--map",
        dest="map_yaml",
        type=Path,
        default=None,
        help="ROS map YAML (with an image: PGM) to draw under the trajectory.",
    )
    replay_parser.add_argument(
        "--duration",
        type=float,
        default=4.0,
        help="Seconds for one loop of the replay animation.",
    )

    record_parser = subparsers.add_parser(
        "record",
        help="Append a JSON run report to an append-only history store for trend tracking.",
    )
    record_parser.add_argument("report", type=Path, help="JSON run report path.")
    record_parser.add_argument("--history", type=Path, required=True, help="History JSONL store to append to.")
    record_parser.add_argument(
        "--label",
        default=None,
        help="Run label, typically a commit SHA. Defaults to the report's generated_at.",
    )
    record_parser.add_argument(
        "--timestamp",
        default=None,
        help="Override the recorded timestamp. Defaults to the report's generated_at.",
    )

    trend_parser = subparsers.add_parser(
        "trend",
        help="Render a history store as a metric trend dashboard.",
    )
    trend_parser.add_argument("history", type=Path, help="History JSONL store path.")
    trend_parser.add_argument("--html-output", type=Path, default=None, help="Optional HTML trend dashboard path.")
    trend_parser.add_argument("--markdown-output", type=Path, default=None, help="Optional Markdown trend summary path.")
    trend_parser.add_argument("--json-output", type=Path, default=None, help="Optional machine-readable trend JSON path.")
    trend_parser.add_argument(
        "--github-summary",
        action="store_true",
        help="Append the Markdown trend summary to the GITHUB_STEP_SUMMARY file.",
    )

    pr_comment_parser = subparsers.add_parser(
        "pr-comment",
        help="Render a compact PR benchmark comment from evaluate/trend JSON.",
    )
    pr_comment_parser.add_argument(
        "--evaluation",
        type=Path,
        required=True,
        metavar="EVALUATION.json",
        help="Leaderboard JSON produced by 'evaluate --json-output'.",
    )
    pr_comment_parser.add_argument(
        "--trend",
        type=Path,
        default=None,
        metavar="TREND.json",
        help="Optional trend JSON produced by 'trend --json-output' for a regression section.",
    )
    pr_comment_parser.add_argument(
        "--title",
        default="Nav2 Benchmark",
        help="Heading shown at the top of the comment.",
    )
    pr_comment_parser.add_argument(
        "--dashboard-url",
        default=None,
        help="Optional URL to a full HTML dashboard, linked in the footer.",
    )
    pr_comment_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the Markdown comment to this path (also printed to stdout).",
    )

    compare_parser = subparsers.add_parser("compare", help="Compare current JSON report against a baseline.")
    compare_parser.add_argument("current", type=Path, help="Current JSON report path.")
    compare_parser.add_argument("--baseline", type=Path, required=True, help="Baseline JSON report path.")
    compare_parser.add_argument(
        "--max-increase-percent",
        action="append",
        default=[],
        metavar="METRIC=PERCENT",
        help="Fail if numeric metric increases by more than this percent. Can be repeated.",
    )
    compare_parser.add_argument(
        "--max-delta",
        action="append",
        default=[],
        metavar="METRIC=DELTA",
        help="Fail if numeric metric increases by more than this absolute delta. Can be repeated.",
    )
    compare_parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Do not fail when a scenario exists in baseline but not current report.",
    )
    compare_parser.add_argument("--output", type=Path, default=None, help="Optional JSON comparison report path.")
    compare_parser.add_argument("--markdown-output", type=Path, default=None, help="Optional Markdown comparison summary path.")
    compare_parser.add_argument(
        "--github-summary",
        action="store_true",
        help="Append a Markdown comparison summary to the GITHUB_STEP_SUMMARY file.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        return _cmd_init(args.target_dir, args.template, args.force)

    if args.command == "doctor":
        return _cmd_doctor(args.check_ros, args.check_gazebo, args.check_ros_graph, args.json)

    if args.command == "report":
        return _cmd_report(
            args.path,
            args.format,
            args.output,
            args.github_summary,
            args.fail_on_failure,
        )

    if args.command == "replay":
        return _cmd_replay(
            report_path=args.report,
            html_output=args.html_output,
            scenarios=set(args.scenario),
            map_yaml=args.map_yaml,
            duration=args.duration,
        )

    if args.command == "record":
        return _cmd_record(args.report, args.history, args.label, args.timestamp)

    if args.command == "trend":
        return _cmd_trend(
            history_path=args.history,
            html_output=args.html_output,
            markdown_output=args.markdown_output,
            json_output=args.json_output,
            github_summary=args.github_summary,
        )

    if args.command == "evaluate":
        return _cmd_evaluate(
            entries=args.entry,
            lower_is_better=args.lower_is_better,
            higher_is_better=args.higher_is_better,
            html_output=args.html_output,
            markdown_output=args.markdown_output,
            json_output=args.json_output,
            github_summary=args.github_summary,
        )

    if args.command == "pr-comment":
        return _cmd_pr_comment(
            evaluation_path=args.evaluation,
            trend_path=args.trend,
            title=args.title,
            dashboard_url=args.dashboard_url,
            output_path=args.output,
        )

    if args.command == "compare":
        return _cmd_compare(
            current_path=args.current,
            baseline_path=args.baseline,
            max_increase_percent=args.max_increase_percent,
            max_delta=args.max_delta,
            allow_missing=args.allow_missing,
            output_path=args.output,
            markdown_output_path=args.markdown_output,
            github_summary=args.github_summary,
        )

    schema_path = args.schema or default_schema_path()
    validator = SchemaValidator.from_file(schema_path)

    if args.command == "lint":
        return _cmd_lint(args.paths, validator)
    if args.command == "list":
        return _cmd_list(args.paths, validator, set(args.tag))
    if args.command == "run":
        mode = "dry-run" if args.dry_run else args.mode
        return _cmd_run(
            args.paths,
            validator,
            set(args.tag),
            mode,
            args.report_dir,
            args.json_report,
            args.junit_report,
            args.trace_report,
            args.markdown_report,
            args.html_report,
            args.github_summary,
            args.sim_startup_timeout,
            args.skip_gazebo_preflight,
            args.wait_for_clock,
            args.clock_timeout,
            args.execute_nav2,
            args.launch_scenario_stack,
            args.wait_for_ros_graph,
            args.ros_graph_timeout,
            args.wait_for_nav2,
            args.nav2_timeout,
            args.wait_for_navigation_data,
            args.navigation_data_timeout,
            args.reset_world,
            args.world_reset_timeout,
            args.execute_simulator_steps,
            args.simulator_step_timeout,
            args.collect_contacts,
            args.contact_topic,
            args.contact_discovery_timeout,
        )

    raise AssertionError(f"Unhandled command: {args.command}")


def _cmd_init(target_dir: Path, template: str, force: bool) -> int:
    try:
        created = init_project(target_dir=target_dir, template=template, force=force)
    except InitError as exc:
        print(f"Init failed: {exc}", file=sys.stderr)
        return 1

    print(f"Initialized {target_dir} with template {template}")
    for path in created:
        print(f"  created: {path}")
    print("Next: nav2_scenario_runner lint scenarios/")
    print("Next: nav2_scenario_runner run scenarios/ --dry-run")
    return 0


def _cmd_doctor(check_ros: bool, check_gazebo: bool, check_ros_graph: bool, json_path: Path | None) -> int:
    report = run_doctor(
        check_ros=check_ros,
        check_gazebo=check_gazebo,
        check_ros_graph=check_ros_graph,
    )
    label = "PASS" if report.passed else "FAIL"
    print(f"Doctor {label}")
    for check in report.checks:
        marker = check.status.upper()
        required = "required" if check.required else "optional"
        print(f"[{marker}] {check.name} ({required}) - {check.message}")

    if json_path:
        write_doctor_report(report, json_path)
        print(f"Doctor report: {json_path}")

    return 0 if report.passed else 1


def _cmd_replay(
    report_path: Path,
    html_output: Path,
    scenarios: set[str],
    map_yaml: Path | None,
    duration: float,
) -> int:
    try:
        report = load_run_report(report_path)
        replay_scenarios = load_replay_scenarios(report, only=scenarios or None)
        map_image = load_map(map_yaml) if map_yaml else None
    except ValueError as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        return 2

    if not replay_scenarios:
        print("Replay failed: no scenarios with trajectories to replay.", file=sys.stderr)
        return 1

    write_text_report(format_replay_html(replay_scenarios, map_image, duration), html_output)
    print(f"Replay HTML: {html_output} ({len(replay_scenarios)} scenario(s))")
    return 0


def _cmd_record(
    report_path: Path,
    history_path: Path,
    label: str | None,
    timestamp: str | None,
) -> int:
    try:
        report = load_run_report(report_path)
        resolved_label = label or str(report.get("generated_at") or "")
        if not resolved_label:
            print("Record failed: no --label provided and report has no generated_at.", file=sys.stderr)
            return 2
        entry = summarize_report(report, label=resolved_label, timestamp=timestamp)
        append_history(history_path, entry)
    except ValueError as exc:
        print(f"Record failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Recorded {resolved_label} to {history_path}: "
        f"{entry.passed}/{entry.total} passed across {len(entry.scenarios)} scenario(s)"
    )
    return 0


def _cmd_trend(
    history_path: Path,
    html_output: Path | None,
    markdown_output: Path | None,
    json_output: Path | None,
    github_summary: bool,
) -> int:
    import json

    try:
        entries = load_history(history_path)
        trend = build_trend(entries)
    except ValueError as exc:
        print(f"Trend failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Trend: {len(trend.labels)} run(s), latest {trend.labels[-1]} "
        f"pass={trend.pass_rates[-1] * 100:.0f}%, {len(trend.metrics)} metric(s)"
    )

    if html_output:
        write_text_report(format_trend_html(trend), html_output)
        print(f"Trend HTML: {html_output}")

    if markdown_output:
        write_text_report(format_trend_markdown(trend), markdown_output)
        print(f"Trend Markdown: {markdown_output}")

    if json_output:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(trend_to_dict(trend), indent=2) + "\n", encoding="utf-8")
        print(f"Trend JSON: {json_output}")

    if github_summary:
        try:
            github_summary_path = _github_summary_path()
        except ValueError as exc:
            print(f"Trend GitHub summary failed: {exc}", file=sys.stderr)
            return 2
        append_text_report(format_trend_markdown(trend), github_summary_path)
        print(f"Trend GitHub summary: {github_summary_path}")

    return 0


def _cmd_evaluate(
    entries: list[str],
    lower_is_better: list[str],
    higher_is_better: list[str],
    html_output: Path | None,
    markdown_output: Path | None,
    json_output: Path | None,
    github_summary: bool,
) -> int:
    import json

    from .evaluate import evaluation_to_dict

    try:
        parsed_entries = [parse_entry(raw) for raw in entries]
        loaded = load_entries(parsed_entries)
    except ValueError as exc:
        print(f"Evaluate failed: {exc}", file=sys.stderr)
        return 2

    directions = MetricDirections()
    for metric in lower_is_better:
        directions.lower_is_better.add(metric)
        directions.higher_is_better.discard(metric)
    for metric in higher_is_better:
        directions.higher_is_better.add(metric)
        directions.lower_is_better.discard(metric)

    evaluation = build_evaluation(loaded, directions)

    print(f"Evaluate: {len(evaluation.configs)} configurations, {len(evaluation.scenario_ids)} scenarios")
    for config in evaluation.configs:
        print(
            f"  {config.rank}. {config.label} "
            f"score={config.composite * 100:.1f} "
            f"pass={config.pass_rate * 100:.0f}% ({config.passed}/{config.total}) "
            f"wins={config.wins}"
        )

    if html_output:
        write_text_report(format_evaluation_html(evaluation), html_output)
        print(f"Evaluation HTML: {html_output}")

    if markdown_output:
        write_text_report(format_evaluation_markdown(evaluation), markdown_output)
        print(f"Evaluation Markdown: {markdown_output}")

    if json_output:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(evaluation_to_dict(evaluation), indent=2) + "\n", encoding="utf-8")
        print(f"Evaluation JSON: {json_output}")

    if github_summary:
        try:
            github_summary_path = _github_summary_path()
        except ValueError as exc:
            print(f"Evaluate GitHub summary failed: {exc}", file=sys.stderr)
            return 2
        append_text_report(format_evaluation_markdown(evaluation), github_summary_path)
        print(f"Evaluation GitHub summary: {github_summary_path}")

    return 0


def _cmd_pr_comment(
    evaluation_path: Path,
    trend_path: Path | None,
    title: str,
    dashboard_url: str | None,
    output_path: Path | None,
) -> int:
    import json

    from .pr_comment import build_comment

    try:
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        trend = (
            json.loads(trend_path.read_text(encoding="utf-8")) if trend_path else None
        )
        body = build_comment(
            evaluation,
            trend,
            title=title,
            dashboard_url=dashboard_url,
        )
    except (OSError, ValueError) as exc:
        print(f"PR comment failed: {exc}", file=sys.stderr)
        return 2

    if output_path:
        write_text_report(body, output_path)
        print(f"PR comment: {output_path}")
    else:
        print(body, end="")
    return 0


def _cmd_compare(
    current_path: Path,
    baseline_path: Path,
    max_increase_percent: list[str],
    max_delta: list[str],
    allow_missing: bool,
    output_path: Path | None,
    markdown_output_path: Path | None,
    github_summary: bool,
) -> int:
    try:
        rules = [
            parse_metric_rule(raw, kind="max_increase_percent")
            for raw in max_increase_percent
        ]
        rules.extend(parse_metric_rule(raw, kind="max_delta") for raw in max_delta)
        report = compare_report_files(
            current_path=current_path,
            baseline_path=baseline_path,
            rules=rules,
            allow_missing=allow_missing,
        )
    except ValueError as exc:
        print(f"Compare failed: {exc}", file=sys.stderr)
        return 2

    label = "PASS" if report.passed else "FAIL"
    print(
        f"Compare {label}: checked={report.checked_scenarios} "
        f"issues={len(report.issues)} new={len(report.new_scenarios)} "
        f"missing={len(report.missing_scenarios)}"
    )
    for issue in report.issues:
        print(f"- {issue.scenario_id} {issue.kind}: {issue.message}")

    if output_path:
        write_compare_report(report, output_path)
        print(f"Compare report: {output_path}")

    if markdown_output_path:
        write_compare_markdown(report, markdown_output_path)
        print(f"Compare Markdown: {markdown_output_path}")

    if github_summary:
        try:
            github_summary_path = _github_summary_path()
        except ValueError as exc:
            print(f"Compare GitHub summary failed: {exc}", file=sys.stderr)
            return 2
        append_text_report(format_compare_markdown(report), github_summary_path)
        print(f"Compare GitHub summary: {github_summary_path}")

    return 0 if report.passed else 1


def _cmd_report(
    path: Path,
    output_format: str,
    output_path: Path | None,
    github_summary: bool,
    fail_on_failure: bool,
) -> int:
    try:
        report = load_run_report(path)
        rendered = format_run_report(report, output_format)
        github_summary_path = _github_summary_path() if github_summary else None
        github_rendered = format_run_report(report, "markdown") if github_summary_path else None
    except ValueError as exc:
        print(f"Report failed: {exc}", file=sys.stderr)
        return 2

    if output_path:
        write_text_report(rendered, output_path)
        print(f"Report summary: {output_path}")
    else:
        print(rendered, end="")

    if github_summary_path and github_rendered:
        append_text_report(github_rendered, github_summary_path)
        print(f"GitHub summary: {github_summary_path}")

    if fail_on_failure and report_has_failures(report):
        return 1
    return 0


def _github_summary_path() -> Path:
    raw_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not raw_path:
        raise ValueError("GITHUB_STEP_SUMMARY is not set.")
    return Path(raw_path)


def _cmd_lint(paths: list[str], validator: SchemaValidator) -> int:
    scenario_paths = discover_scenarios(paths)
    if not scenario_paths:
        print("No scenario YAML files found.", file=sys.stderr)
        return 1

    failed = False
    for path in scenario_paths:
        result = _load_and_validate(path, validator)
        if result.errors:
            failed = True
            print(f"FAIL {path}")
            for error in result.errors:
                print(f"  - {error}")
        else:
            print(f"OK   {path}")

    return 1 if failed else 0


def _cmd_list(paths: list[str], validator: SchemaValidator, tags: set[str]) -> int:
    scenario_paths = discover_scenarios(paths)
    if not scenario_paths:
        print("No scenario YAML files found.", file=sys.stderr)
        return 1

    exit_code = 0
    for path in scenario_paths:
        result = _load_and_validate(path, validator)
        if result.errors:
            exit_code = 1
            print(f"INVALID {path}")
            for error in result.errors:
                print(f"  - {error}")
            continue
        if not result.scenario:
            continue
        if tags and not tags.issubset(result.scenario.tags):
            continue
        print(f"{result.scenario.scenario_id}\t{path}\t[{', '.join(sorted(result.scenario.tags))}]")

    return exit_code


def _cmd_run(
    paths: list[str],
    validator: SchemaValidator,
    tags: set[str],
    mode: str,
    report_dir: Path,
    json_report_name: str,
    junit_report_name: str,
    trace_report_name: str | None,
    markdown_report_name: str | None,
    html_report_name: str | None,
    github_summary: bool,
    sim_startup_timeout: float,
    skip_gazebo_preflight: bool,
    wait_for_clock: bool,
    clock_timeout: float,
    execute_nav2: bool,
    launch_scenario_stack: bool,
    wait_for_ros_graph: bool,
    ros_graph_timeout: float,
    wait_for_nav2: bool,
    nav2_timeout: float,
    wait_for_navigation_data: bool,
    navigation_data_timeout: float,
    reset_world: bool,
    world_reset_timeout: float,
    execute_simulator_steps: bool,
    simulator_step_timeout: float,
    collect_contacts: bool,
    contact_topics: list[str],
    contact_discovery_timeout: float,
) -> int:
    scenario_paths = discover_scenarios(paths)
    if not scenario_paths:
        print("No scenario YAML files found.", file=sys.stderr)
        return 1

    load_results = [_load_and_validate(path, validator) for path in scenario_paths]
    valid_scenarios = []
    failed = False

    for result in load_results:
        if result.errors:
            failed = True
            print(f"INVALID {result.path}")
            for error in result.errors:
                print(f"  - {error}")
            continue
        if result.scenario and (not tags or tags.issubset(result.scenario.tags)):
            valid_scenarios.append(result.scenario)

    if failed:
        return 1
    if not valid_scenarios:
        print("No scenarios matched the requested filters.", file=sys.stderr)
        return 1

    if mode == "dry-run":
        report = dry_run(valid_scenarios)
        for scenario in report.scenarios:
            print(
                f"DRY-RUN PASS {scenario.name} "
                f"steps={scenario.step_count} assertions={scenario.assertion_count}"
            )
        return _write_report_and_exit(
            report,
            report_dir,
            json_report_name,
            junit_report_name,
            trace_report_name,
            markdown_report_name,
            html_report_name,
            github_summary,
        )

    if mode == "attach":
        try:
            from .backends.ros import RosAttachBackend

            report = run_with_backend_factory(
                valid_scenarios,
                mode="attach",
                backend_factory=RosAttachBackend.from_scenario,
            )
        except BackendUnavailable as exc:
            print(f"Attach backend unavailable: {exc}", file=sys.stderr)
            return 2

        for scenario in report.scenarios:
            label = "PASS" if scenario.status == "passed" else "FAIL"
            print(
                f"{label} {scenario.name} "
                f"steps={scenario.step_count} assertions={scenario.assertion_count}"
            )
            if scenario.failure_reason:
                print(f"  reason: {scenario.failure_reason}")
        return _write_report_and_exit(
            report,
            report_dir,
            json_report_name,
            junit_report_name,
            trace_report_name,
            markdown_report_name,
            html_report_name,
            github_summary,
        )

    if mode == "gazebo-sim":
        if not skip_gazebo_preflight:
            doctor_report = run_doctor(check_gazebo=True)
            if not doctor_report.passed:
                print("Gazebo Sim backend unavailable:", file=sys.stderr)
                for check in doctor_report.checks:
                    if check.required and check.status != "pass":
                        print(f"  - {check.name}: {check.message}", file=sys.stderr)
                return 2

        from .backends.gazebo_sim import run_gazebo_sim_lifecycle

        report = run_gazebo_sim_lifecycle(
            valid_scenarios,
            report_dir=report_dir,
            startup_timeout=sim_startup_timeout,
            preflight_skipped=skip_gazebo_preflight,
            wait_for_clock=wait_for_clock,
            clock_timeout=clock_timeout,
            execute_nav2=execute_nav2,
            launch_scenario_stack=launch_scenario_stack,
            wait_for_ros_graph=wait_for_ros_graph,
            ros_graph_timeout=ros_graph_timeout,
            wait_for_nav2=wait_for_nav2,
            nav2_timeout=nav2_timeout,
            wait_for_navigation_data=wait_for_navigation_data,
            navigation_data_timeout=navigation_data_timeout,
            reset_world=reset_world,
            world_reset_timeout=world_reset_timeout,
            execute_simulator_steps=execute_simulator_steps,
            simulator_step_timeout=simulator_step_timeout,
            collect_contacts=collect_contacts,
            contact_topics=contact_topics,
            contact_discovery_timeout=contact_discovery_timeout,
        )
        for scenario in report.scenarios:
            label = "PASS" if scenario.status == "passed" else "FAIL"
            print(f"GAZEBO-SIM {label} {scenario.name}")
            if scenario.failure_reason:
                print(f"  reason: {scenario.failure_reason}")
        return _write_report_and_exit(
            report,
            report_dir,
            json_report_name,
            junit_report_name,
            trace_report_name,
            markdown_report_name,
            html_report_name,
            github_summary,
        )

    raise AssertionError(f"Unhandled run mode: {mode}")


def _write_report_and_exit(
    report,
    report_dir: Path,
    json_report_name: str,
    junit_report_name: str,
    trace_report_name: str | None,
    markdown_report_name: str | None,
    html_report_name: str | None,
    github_summary: bool,
) -> int:
    print(f"Summary: {report.total} scenario(s), {report.passed} passed, {report.failed} failed")

    json_report_path = report_dir / json_report_name
    write_json_report(report, json_report_path)
    print(f"JSON report: {json_report_path}")

    junit_report_path = report_dir / junit_report_name
    write_junit_report(report, junit_report_path)
    print(f"JUnit report: {junit_report_path}")

    render_exit_code = _write_optional_run_reports(
        report,
        report_dir,
        trace_report_name,
        markdown_report_name,
        html_report_name,
        github_summary,
    )
    if render_exit_code:
        return render_exit_code

    return 0 if report.failed == 0 else 1


def _write_optional_run_reports(
    report,
    report_dir: Path,
    trace_report_name: str | None,
    markdown_report_name: str | None,
    html_report_name: str | None,
    github_summary: bool,
) -> int:
    report_dict = asdict(report)

    if trace_report_name:
        trace_report_path = report_dir / trace_report_name
        write_trace_report(report, trace_report_path)
        print(f"Trace report: {trace_report_path}")

    if markdown_report_name:
        markdown_report_path = report_dir / markdown_report_name
        write_text_report(format_run_report(report_dict, "markdown"), markdown_report_path)
        print(f"Markdown report: {markdown_report_path}")

    if html_report_name:
        html_report_path = report_dir / html_report_name
        write_text_report(format_run_report(report_dict, "html"), html_report_path)
        print(f"HTML report: {html_report_path}")

    if github_summary:
        try:
            github_summary_path = _github_summary_path()
        except ValueError as exc:
            print(f"GitHub summary failed: {exc}", file=sys.stderr)
            return 2
        append_text_report(format_run_report(report_dict, "markdown"), github_summary_path)
        print(f"GitHub summary: {github_summary_path}")

    return 0


def _load_and_validate(path: Path, validator: SchemaValidator):
    result = load_scenario(path)
    if result.errors or not result.scenario:
        return result

    validation_errors = validator.validate(result.scenario.document)
    if validation_errors:
        result.errors.extend(validation_errors)
    return result
