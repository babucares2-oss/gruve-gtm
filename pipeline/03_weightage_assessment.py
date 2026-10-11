#!/usr/bin/env python3
"""Stage 3: score enriched leads using category and subcategory weights."""

import argparse
import csv
import json
import re
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def number_from(value: str) -> float | None:
    match = re.search(r"\d[\d,]*", value or "")
    return float(match.group().replace(",", "")) if match else None


def normalized_words(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def subcategory_score(value: str, rule: dict) -> float:
    value = (value or "").strip()
    maximum = float(rule["max_points"])

    if rule["type"] == "category":
        values = rule.get("values", {})
        score = float(next(
            (points for label, points in values.items() if label.casefold() == value.casefold()),
            rule.get("default", 0),
        ))
    elif rule["type"] == "number_range":
        number = number_from(value)
        score = 0.0
        if number is not None:
            for band in rule["bands"]:
                if number >= band.get("min", float("-inf")) and number < band.get("max", float("inf")):
                    score = float(band["score"])
                    break
    elif rule["type"] == "keyword":
        lowered = value.casefold()
        score = sum(
            float(points) for keyword, points in rule.get("keywords", {}).items()
            if keyword.casefold() in lowered
        )
    elif rule["type"] == "timeline":
        score = 0.0
        quarter = re.search(r"\bq([1-4])\s*[,/-]?\s*(20\d{2})\b", value, re.IGNORECASE)
        if quarter:
            quarter_number = int(quarter.group(1))
            year = int(quarter.group(2))
            end_month = quarter_number * 3
            end_day = monthrange(year, end_month)[1]
            quarter_end = date(year, end_month, end_day)
            score = float(
                rule["future_quarter_score"]
                if quarter_end >= date.today()
                else rule.get("past_quarter_score", 0)
            )
    elif rule["type"] == "title_priority":
        normalized_title = f" {normalized_words(value)} "
        score = 0.0
        for tier in rule["tiers"]:
            if any(
                f" {normalized_words(match)} " in normalized_title
                for match in tier["matches"]
            ):
                score = float(tier["score"])
                break
    else:
        raise ValueError(f"Unsupported scoring type: {rule['type']}")

    return min(max(score, 0.0), maximum)


def deal_category(subcategory_points: dict[str, float], category_points: dict[str, float], config: dict) -> str:
    metrics = {**subcategory_points, **category_points}
    metrics.update({f"{name}_points": score for name, score in metrics.copy().items()})
    operators = {
        "gt": lambda actual, expected: actual > expected,
        "gte": lambda actual, expected: actual >= expected,
        "eq": lambda actual, expected: actual == expected,
        "lt": lambda actual, expected: actual < expected,
        "lte": lambda actual, expected: actual <= expected,
    }

    def matches(condition: dict) -> bool:
        operator = operators.get(condition.get("operator"))
        if operator is None:
            raise ValueError(f"Unsupported deal category operator: {condition.get('operator')}")
        metric = condition["metric"]
        if metric not in metrics:
            raise ValueError(f"Unknown deal category metric: {metric}")
        return operator(metrics[metric], float(condition["value"]))

    for rule in config.get("deal_category_rules", []):
        conditions = rule.get("any")
        if (any(matches(condition) for condition in conditions) if conditions is not None else matches(rule)):
            return rule["label"]
    return config.get("deal_category_default", "Interesting Deal")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "output" / "enriched_leads.csv")
    parser.add_argument("--config", type=Path, default=ROOT / "scoring_config.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "scored_leads.csv")
    args = parser.parse_args()

    try:
        with args.config.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
        categories = config["major_categories"]
        if sum(float(category["weight_pct"]) for category in categories) > 100:
            parser.error("The sum of major category weights cannot exceed 100%.")
        for category in categories:
            subcategory_max = sum(float(item["max_points"]) for item in category["subcategories"])
            if subcategory_max > float(category["weight_pct"]):
                parser.error(
                    f"Subcategory maximums for {category['name']} total {subcategory_max}, "
                    f"above its {category['weight_pct']}% weight."
                )

        subcategories = [item for category in categories for item in category["subcategories"]]
        with args.input.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            required = {"lead_id", "company_name"} | {item["field"] for item in subcategories}
            missing = required - set(reader.fieldnames or [])
            if missing:
                parser.error("CSV is missing required column(s): " + ", ".join(sorted(missing)))

            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8", newline="") as destination:
                writer = csv.writer(destination, lineterminator="\n")
                passthrough = [
                    "lead_id", "company_name", *[item["field"] for item in subcategories],
                    "record_id", "company_id", "title", "industry_type", "first_name", "last_name",
                    "company_size", "signal_message", "company_request_count",
                ]
                passthrough = list(dict.fromkeys(passthrough))
                points_columns = [f"{item['name']}_points" for item in subcategories]
                category_columns = [f"{category['name']}_points" for category in categories]
                writer.writerow([*passthrough, *points_columns, *category_columns, "score_pct", "deal_category"])

                for row in reader:
                    subcategory_points = {
                        item["name"]: subcategory_score(row.get(item["field"], ""), item)
                        for item in subcategories
                    }
                    category_points = {
                        category["name"]: min(
                            sum(subcategory_points[item["name"]] for item in category["subcategories"]),
                            float(category["weight_pct"]),
                        )
                        for category in categories
                    }
                    total = sum(category_points.values())
                    label = deal_category(subcategory_points, category_points, config)
                    writer.writerow([
                        *[row.get(field, "") for field in passthrough],
                        *[subcategory_points[item["name"]] for item in subcategories],
                        *[category_points[category["name"]] for category in categories],
                        total,
                        label,
                    ])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"Could not score leads: {error}", file=sys.stderr)
        return 1

    print(f"Scored leads saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
