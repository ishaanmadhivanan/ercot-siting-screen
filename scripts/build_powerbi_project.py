"""Generate the Phase 5 Power BI project (PBIP: text files instead of one .pbix).

    python scripts/build_powerbi_project.py

Writes powerbi/ercot_siting_v2.pbip plus its .SemanticModel (tables, measures,
weight sliders) and .Report (pages, visuals). Re-running overwrites the files in those
folders, so make report changes either here or, once you start editing in
Power BI Desktop, stop using this script and edit in Desktop.

Why a generator: there are 19 weight sliders and each needs a table, a
measure and a slicer. Writing them by hand invites typos, and a .pbix is a
binary that Git cannot diff.

The model matches the SQL layer, which is TALL (one row per county per
factor in rpt.county_factor_score), so the weighted score is a SUMX over the
factors a county has, not a sum of 19 columns.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "powerbi"
NAME = "ercot_siting_v2"
SM = OUT / f"{NAME}.SemanticModel"
RP = OUT / f"{NAME}.Report"
THEME_SRC = None  # filled in from the old .pbix if present

SERVER_DEFAULT = r"localhost\SQLEXPRESS"
DB_DEFAULT = "ErcotSiting"

# ---------------------------------------------------------------- factors
# key, label (shown on the slider), default weight 0-10, slider min.
# Defaults reproduce the 'gas' preset in dim.score_weight (weights x 20,
# rounded); everything else starts at 0 so the user opts in.
# queue_congestion is the one factor with no fixed good direction, so its
# slider runs -10..10: a negative weight means "fewer MW in the queue is
# better" (the score is flipped for that factor).
FACTORS = [
    ("installed_mw", "Existing generation capacity", 3, 0),
    ("retiring_mw", "Capacity retiring by 2030", 0, 0),
    ("capacity_factor", "Realised capacity factor", 0, 0),
    ("generation_trend", "Generation trend 2020-2024", 2, 0),
    ("queue_congestion", "Interconnection queue (negative = fewer is better)", 0, -10),
    ("queue_attrition", "Queue attrition rate", 2, 0),
    ("aging_thermal_mw", "Gas and coal 40+ years old", 5, 0),
    ("gas_queue_mw", "Active gas queue", 4, 0),
    ("gas_capacity_factor", "Gas fleet capacity factor", 2, 0),
    ("pop_density", "Population density", 2, 0),
    ("land_large_tract_share", "Share of land in large tracts", 0, 0),
    ("land_owner_density", "Landowner density", 0, 0),
    ("land_parcels_500ac", "Parcels of 500+ acres", 0, 0),
    ("ozone_severity", "Ozone nonattainment severity", 0, 0),
    ("gas_pipe_miles", "Gas transmission pipe", 0, 0),
    ("gas_pipe_large_miles", "Large gas pipe (20 in and up)", 0, 0),
    ("gas_pipe_interstate_miles", "Interstate gas pipe", 0, 0),
    ("gas_pipe_operators", "Gas pipeline operators", 0, 0),
    ("gas_gathering_miles", "Gas gathering pipe", 0, 0),
]
assert len(FACTORS) == 19


def wtable(key):
    return f"W {key}"


def wmeasure(key):
    return f"W {key} Value"


# ---------------------------------------------------------------- helpers
def hid(*parts):
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]


def tabs(n):
    return "\t" * n


def q(name):
    """TMDL identifier: quote when it has anything but letters/digits/_."""
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


# ---------------------------------------------------------------- model
TYPES = {
    "string": ("text", "string", "none"),
    "int": ("Int64.Type", "int64", "none"),
    "num": ("type number", "double", "none"),
    "date": ("type date", "dateTime", "none"),
}

# name -> list of (col, kind, extra) ; SQL is one line on purpose.
TABLES = {
    "County": dict(
        sql="SELECT county_fips, county_name, county_name + ' County, Texas' AS map_label, "
            "population, land_area_sqmi FROM dim.county WHERE in_ercot = 1",
        cols=[("county_fips", "string"), ("county_name", "string"), ("map_label", "string"),
              ("population", "int"), ("land_area_sqmi", "num")],
    ),
    "county_factor_score": dict(
        sql="SELECT county_fips, county_name, factor_key, factor_label, category, unit, "
            "raw_value, better_direction, score_transform, factor_score FROM rpt.county_factor_score",
        cols=[("county_fips", "string"), ("county_name", "string"), ("factor_key", "string"),
              ("factor_label", "string"), ("category", "string"), ("unit", "string"),
              ("raw_value", "num"), ("better_direction", "string"), ("score_transform", "string"),
              ("factor_score", "num")],
    ),
    "county_filter": dict(
        sql="SELECT a.county_fips, "
            "MAX(CASE WHEN a.attribute_key = 'ozone_classification' THEN a.value_text END) AS ozone_class, "
            "MAX(CASE WHEN a.attribute_key = 'nox_offset_ratio' THEN a.value_num END) AS nox_offset_ratio, "
            "MAX(CASE WHEN a.attribute_key = 'nox_offset_cost_per_tpy' THEN a.value_num END) AS nox_offset_cost_per_tpy, "
            "MAX(CASE WHEN a.attribute_key = 'nox_credit_trades' THEN a.value_num END) AS nox_credit_trades, "
            "MAX(CASE WHEN a.attribute_key = 'land_parcel_coverage' THEN a.value_num END) AS land_parcel_coverage, "
            "MAX(CASE WHEN a.attribute_key = 'land_industrial_acres' THEN a.value_num END) AS land_industrial_acres, "
            "MAX(CASE WHEN a.attribute_key = 'lng_terminal_count' THEN a.value_num END) AS lng_terminal_count "
            "FROM fact.county_attribute a JOIN dim.county c ON c.county_fips = a.county_fips "
            "WHERE c.in_ercot = 1 GROUP BY a.county_fips",
        cols=[("county_fips", "string"), ("ozone_class", "string"), ("nox_offset_ratio", "num"),
              ("nox_offset_cost_per_tpy", "num"), ("nox_credit_trades", "num"),
              ("land_parcel_coverage", "num"), ("land_industrial_acres", "num"),
              ("lng_terminal_count", "num")],
    ),
    "pipeline_segment": dict(
        sql="SELECT p.county_fips, p.operator_name, p.system_name, p.diameter_in, p.interstate, p.miles "
            "FROM fact.pipeline_segment p JOIN dim.county c ON c.county_fips = p.county_fips "
            "WHERE c.in_ercot = 1",
        cols=[("county_fips", "string"), ("operator_name", "string"), ("system_name", "string"),
              ("diameter_in", "num"), ("interstate", "string"), ("miles", "num")],
    ),
    "plant": dict(
        sql="SELECT g.county_fips, g.plant_code, g.generator_id, g.plant_name, g.technology, "
            "g.nameplate_mw, g.operating_year, g.latitude, g.longitude "
            "FROM fact.generator_capacity g JOIN dim.county c ON c.county_fips = g.county_fips "
            "WHERE c.in_ercot = 1 AND g.status_group = 'Operating' "
            "AND g.data_vintage_year = (SELECT MAX(data_vintage_year) FROM fact.generator_capacity)",
        cols=[("county_fips", "string"), ("plant_code", "int"), ("generator_id", "string"),
              ("plant_name", "string"), ("technology", "string"), ("nameplate_mw", "num"),
              ("operating_year", "int"), ("latitude", "num"), ("longitude", "num")],
    ),
    "metric": dict(
        sql="SELECT metric_key, label, category, metric_type, unit, better_direction, source_name, "
            "data_date, caveat FROM dim.metric",
        cols=[("metric_key", "string"), ("label", "string"), ("category", "string"),
              ("metric_type", "string"), ("unit", "string"), ("better_direction", "string"),
              ("source_name", "string"), ("data_date", "date"), ("caveat", "string")],
    ),
}

FORMATS = {"factor_score": "0.0", "raw_value": "#,##0.00", "miles": "#,##0.0",
           "nameplate_mw": "#,##0.0", "population": "#,##0", "diameter_in": "0.0",
           "land_area_sqmi": "#,##0.0", "nox_offset_cost_per_tpy": "$#,##0",
           "nox_offset_ratio": "0.0", "land_parcel_coverage": "0.00"}


def m_source(spec):
    steps = ",".join('{"%s", %s}' % (c, TYPES[k][0]) for c, k in spec["cols"])
    return [
        "let",
        "\tSource = Sql.Database(ServerName, DatabaseName, [Query = \"%s\"])," % spec["sql"].replace('"', '""'),
        "\tTyped = Table.TransformColumnTypes(Source, {%s})" % steps,
        "in",
        "\tTyped",
    ]


def write_table(name, spec, extra_columns="", extra_measures=""):
    L = [f"table {q(name)}", ""]
    for c, k in spec["cols"]:
        L.append(f"\tcolumn {q(c)}")
        L.append(f"\t\tdataType: {TYPES[k][1]}")
        if c in FORMATS:
            L.append(f"\t\tformatString: {FORMATS[c]}")
        if c == "map_label":
            L.append("\t\tdataCategory: County")
        if c in ("latitude",):
            L.append("\t\tdataCategory: Latitude")
        if c in ("longitude",):
            L.append("\t\tdataCategory: Longitude")
        L.append(f"\t\tsummarizeBy: {'sum' if k in ('num',) and c in ('miles','nameplate_mw') else 'none'}")
        L.append(f"\t\tsourceColumn: {c}")
        L.append("")
    L.append(extra_columns)
    L.append(extra_measures)
    L.append(f"\tpartition {q(name)} = m")
    L.append("\t\tmode: import")
    L.append("\t\tsource =")
    for line in m_source(spec):
        L.append("\t\t\t\t" + line)
    L.append("")
    return "\n".join(L) + "\n"


def measure(name, dax, fmt=None, desc=None):
    L = []
    if desc:
        L.append(f"\t/// {desc}")
    L.append(f"\tmeasure {q(name)} = ```")
    for line in dax.strip("\n").split("\n"):
        L.append("\t\t\t" + line)
    L.append("\t\t\t```")
    if fmt:
        L.append(f"\t\tformatString: {fmt}")
    L.append("")
    return "\n".join(L) + "\n"


def county_measures():
    switch_lines = ",\n".join(f'        "{k}", [{wmeasure(k)}]' for k, *_ in FACTORS)
    out = []
    out.append(measure(
        "Weight For Factor",
        "SWITCH (\n    SELECTEDVALUE ( county_factor_score[factor_key] ),\n"
        + switch_lines + ",\n        0\n)",
        "0",
        "Reads the slider for whichever factor is in the current row. Used by My Score."))
    out.append(measure(
        "My Score",
        """
VAR f =
    ADDCOLUMNS (
        VALUES ( county_factor_score[factor_key] ),
        "@w", [Weight For Factor],
        "@s", CALCULATE ( AVERAGE ( county_factor_score[factor_score] ) )
    )
-- A positive weight rewards a high factor score; a negative weight rewards a low one.
-- Factors a county has no score for are left out of BOTH the top and the bottom,
-- so a missing value never counts as a zero.
VAR numer =
    SUMX ( f, IF ( ISBLANK ( [@s] ) || [@w] = 0, 0,
                   IF ( [@w] > 0, [@w] * [@s], -[@w] * ( 100 - [@s] ) ) ) )
VAR denom =
    SUMX ( f, IF ( ISBLANK ( [@s] ), 0, ABS ( [@w] ) ) )
RETURN
    DIVIDE ( numer, denom )
""", "0.0", "Weighted average of the factor scores (0-100) using the sliders."))
    out.append(measure(
        "My Rank",
        "IF ( ISBLANK ( [My Score] ), BLANK (),\n"
        "     RANKX ( ALLSELECTED ( County[county_name] ), [My Score], , DESC, DENSE ) )",
        "0", "1 = best county among those currently shown."))
    out.append(measure(
        "Weight Used %",
        """
VAR f =
    ADDCOLUMNS (
        VALUES ( county_factor_score[factor_key] ),
        "@w", [Weight For Factor],
        "@s", CALCULATE ( AVERAGE ( county_factor_score[factor_score] ) )
    )
RETURN
    DIVIDE (
        SUMX ( f, IF ( ISBLANK ( [@s] ), 0, ABS ( [@w] ) ) ),
        SUMX ( f, ABS ( [@w] ) )
    )
""", "0%", "Share of your slider weight the county actually has data for. Below 100% means a factor was missing and the score is based on the rest."))
    out.append(measure(
        "Layer Score",
        "IF ( HASONEVALUE ( county_factor_score[factor_label] ),\n"
        "     AVERAGE ( county_factor_score[factor_score] ) )",
        "0.0", "0-100 score for the single factor picked on the Single factor page."))
    out.append(measure(
        "Layer Raw Value",
        "IF ( HASONEVALUE ( county_factor_score[factor_label] ),\n"
        "     AVERAGE ( county_factor_score[raw_value] ) )",
        "#,##0.00", "The underlying number before scaling, in the factor's own unit."))
    out.append(measure(
        "Layer Title",
        'SELECTEDVALUE ( county_factor_score[factor_label], "Pick one factor on the left" )'
        '\n    & IF ( HASONEVALUE ( county_factor_score[unit] ), " (" & SELECTEDVALUE ( county_factor_score[unit] ) & ")", "" )'))
    out.append(measure("Pipe Miles", "SUM ( pipeline_segment[miles] )", "#,##0.0"))
    out.append(measure("Plant MW", "SUM ( plant[nameplate_mw] )", "#,##0"))
    return "".join(out)


def write_model():
    # No rmtree: it can fail on synced/locked folders. Files are overwritten in place.
    (SM / "definition" / "tables").mkdir(parents=True, exist_ok=True)
    (SM / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}, indent=2))
    (SM / "definition" / "database.tmdl").write_text(
        f"database {NAME}\n\tcompatibilityLevel: 1600\n")
    refs = list(TABLES) + [wtable(k) for k, *_ in FACTORS]
    (SM / "definition" / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
        "\tdiscourageImplicitMeasures\n\n" + "\n".join(f"ref table {q(t)}" for t in refs) + "\n")
    (SM / "definition" / "expressions.tmdl").write_text(
        f'expression ServerName = "{SERVER_DEFAULT}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f'\tlineageTag: 5a1e0c3e-0001-4a00-9000-000000000001\n\n'
        f'expression DatabaseName = "{DB_DEFAULT}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f'\tlineageTag: 5a1e0c3e-0001-4a00-9000-000000000002\n')

    for name, spec in TABLES.items():
        extra_cols, extra_meas = "", ""
        if name == "County":
            extra_meas = county_measures()
        if name == "county_filter":
            extra_cols = ("\tcolumn 'Ozone Status' = IF ( county_filter[ozone_class] = \"Attainment\", \"Attainment\", \"Nonattainment\" )\n"
                          "\t\tdataType: string\n\t\tsummarizeBy: none\n\n")
        (SM / "definition" / "tables" / f"{name}.tmdl").write_text(
            write_table(name, spec, extra_cols, extra_meas))

    for key, label, default, lo in FACTORS:
        t = wtable(key)
        txt = (
            f"table {q(t)}\n\tisHidden\n\n"
            f"\tcolumn {q(label)}\n\t\tdataType: int64\n\t\tsourceColumn: [Value]\n\t\tsummarizeBy: none\n\n"
            + measure(wmeasure(key), f"SELECTEDVALUE ( {q(t)}[{label}], {default} )", "0")
            + f"\tpartition {q(t)} = calculated\n\t\tmode: import\n\t\tsource = GENERATESERIES ( {lo}, 10, 1 )\n"
        )
        (SM / "definition" / "tables" / f"{t}.tmdl").write_text(txt)

    rels = [
        ("score_to_county", "county_factor_score.county_fips", "County.county_fips"),
        ("filter_to_county", "county_filter.county_fips", "County.county_fips"),
        ("pipe_to_county", "pipeline_segment.county_fips", "County.county_fips"),
        ("plant_to_county", "plant.county_fips", "County.county_fips"),
    ]
    (SM / "definition" / "relationships.tmdl").write_text(
        "\n".join(f"relationship {n}\n\tfromColumn: {a}\n\ttoColumn: {b}\n" for n, a, b in rels))


# ---------------------------------------------------------------- report
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"


def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mea(entity, prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(field, entity, prop, active=None):
    p = {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if active:
        p["active"] = True
    return p


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def pos(x, y, w, h, z):
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}


def visual(name, position, vis, filters=None):
    d = {"$schema": SCHEMA + "visualContainer/2.12.0/schema.json", "name": name,
         "position": position, "visual": vis}
    if filters:
        d["filterConfig"] = {"filters": filters}
    return d


def slicer(page, entity, prop, position, mode, preset=None, single=False, multi_literal=None):
    name = hid(page, "slicer", entity, prop)
    objects = {"data": [{"properties": {"mode": lit(f"'{mode}'")}}]}
    if single:
        objects["selection"] = [{"properties": {"strictSingleSelect": lit("true")}}]
    if preset is not None:
        objects["general"] = [{"properties": {"filter": {"filter": {
            "Version": 2, "From": [{"Name": "s", "Entity": entity, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": prop}}],
                "Values": [[{"Literal": {"Value": preset}}]]}}}]}}}}]
    vis = {"visualType": "slicer",
           "query": {"queryState": {"Values": {"projections": [proj(col(entity, prop), entity, prop, True)]}}},
           "objects": objects, "drillFilterOtherVisuals": True}
    f = [{"name": hid(name, "f"), "field": col(entity, prop), "type": "Categorical"}]
    return name, visual(name, position, vis, f)


GRADIENT = lambda field: {"solid": {"color": {"expr": {"FillRule": {"Input": field, "FillRule": {
    "linearGradient2": {
        "min": {"color": {"Literal": {"Value": "'#E3EEF9'"}}},
        "max": {"color": {"Literal": {"Value": "'#08519C'"}}},
        "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'specificColor'"}},
                                 "color": {"Literal": {"Value": "'#D9D9D9'"}}}}}}}}}}


def filled_map(page, position, color_measure, tooltips):
    name = hid(page, "map")
    cat = col("County", "map_label")
    qs = {"Category": {"projections": [proj(cat, "County", "map_label", True)]}}
    if tooltips:
        qs["Tooltips"] = {"projections": [proj(f, e, p) for f, e, p in tooltips]}
    vis = {"visualType": "filledMap", "query": {"queryState": qs},
           "objects": {"dataPoint": [{"properties": {"fill": GRADIENT(mea("County", color_measure))},
                                      "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]},
           "drillFilterOtherVisuals": True}
    return name, visual(name, position, vis,
                        [{"name": hid(name, "f"), "field": cat, "type": "Categorical"}])


def table_visual(page, key, position, cols, sort):
    """cols: list of (kind, entity, prop). sort: (kind, entity, prop, dir)."""
    name = hid(page, "table", key)
    fields = [(col if k == "c" else mea)(e, p) for k, e, p in cols]
    projs = [proj(f, e, p) for f, (k, e, p) in zip(fields, cols)]
    sk, se, sp, sd = sort
    vis = {"visualType": "tableEx", "query": {
        "queryState": {"Values": {"projections": projs}},
        "sortDefinition": {"sort": [{"field": (col if sk == "c" else mea)(se, sp), "direction": sd}],
                           "isDefaultSort": True}},
        "drillFilterOtherVisuals": True}
    return name, visual(name, position, vis)


def top_bar(page, position, n=15):
    name = hid(page, "bar")
    cat = col("County", "county_name")
    val = mea("County", "My Score")
    vis = {"visualType": "clusteredBarChart", "query": {
        "queryState": {"Category": {"projections": [proj(cat, "County", "county_name", True)]},
                       "Y": {"projections": [proj(val, "County", "My Score")]}},
        "sortDefinition": {"sort": [{"field": val, "direction": "Descending"}], "isDefaultSort": True}},
        "drillFilterOtherVisuals": True}
    topn = {"name": hid(name, "topn"), "field": cat, "type": "TopN", "filter": {
        "Version": 2,
        "From": [{"Name": "subquery", "Expression": {"Subquery": {"Query": {
            "Version": 2, "From": [{"Name": "c", "Entity": "County", "Type": 0}],
            "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "c"}}, "Property": "county_name"},
                        "Name": "field"}],
            "OrderBy": [{"Direction": 2, "Expression": {"Measure": {
                "Expression": {"SourceRef": {"Source": "c"}}, "Property": "My Score"}}}],
            "Top": n}}}, "Type": 2},
                 {"Name": "c", "Entity": "County", "Type": 0}],
        "Where": [{"Condition": {"In": {
            "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "c"}}, "Property": "county_name"}}],
            "Table": {"SourceRef": {"Source": "subquery"}}}}}]}}
    return name, visual(name, position, vis, [topn])


def card(page, key, position, field, entity, prop):
    name = hid(page, "card", key)
    vis = {"visualType": "card", "query": {"queryState": {"Values": {
        "projections": [proj(field, entity, prop)]}}}, "drillFilterOtherVisuals": True}
    return name, visual(name, position, vis)


def write_page(pdir, page_name, display, visuals, extra=None):
    d = {"$schema": SCHEMA + "page/2.1.0/schema.json", "name": page_name, "displayName": display,
         "displayOption": "FitToPage", "height": 1080, "width": 1920}
    if extra:
        d.update(extra)
    p = RP / "definition" / "pages" / page_name
    p.mkdir(parents=True, exist_ok=True)
    (p / "page.json").write_text(json.dumps(d, indent=2))
    for vname, v in visuals:
        vd = p / "visuals" / vname
        vd.mkdir(parents=True, exist_ok=True)
        (vd / "visual.json").write_text(json.dumps(v, indent=2))


def write_report():
    (RP / "definition" / "pages").mkdir(parents=True, exist_ok=True)
    (RP / "definition.pbir").write_text(json.dumps({
        "$schema": SCHEMA.replace("report/definition/", "report/definitionProperties/") + "2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2))
    (RP / "definition" / "version.json").write_text(json.dumps(
        {"$schema": SCHEMA + "versionMetadata/1.0.0/schema.json", "version": "2.0.0"}, indent=2))
    (RP / "definition" / "report.json").write_text(json.dumps({
        "$schema": SCHEMA + "report/3.3.0/schema.json",
        "themeCollection": {"baseTheme": {"name": "Fluent2-CY26SU08", "reportVersionAtImport": {
            "visual": "2.12.0", "report": "3.4.0", "page": "2.3.1"}, "type": "SharedResources"}},
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources", "items": [
            {"name": "Fluent2-CY26SU08", "path": "BaseThemes/Fluent2-CY26SU08.json", "type": "BaseTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}}, indent=2))
    if THEME_SRC and THEME_SRC.exists():
        dst = RP / "StaticResources" / "SharedResources" / "BaseThemes"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(THEME_SRC, dst / "Fluent2-CY26SU08.json")

    P1, P2, P3, P4 = (hid("page", s) for s in ("score", "factor", "detail", "catalog"))
    (RP / "definition" / "pages" / "pages.json").parent.mkdir(parents=True, exist_ok=True)
    (RP / "definition" / "pages" / "pages.json").write_text(json.dumps({
        "$schema": SCHEMA + "pagesMetadata/1.1.0/schema.json",
        "pageOrder": [P1, P2, P3, P4], "activePageName": P1}, indent=2))

    # ---- page 1: weights, map, ranking, filters
    vs, z = [], 1000
    cw, ch = 195, 104
    for i, (key, label, default, lo) in enumerate(FACTORS):
        c, r = divmod(i, 10)
        vs.append(slicer(P1, wtable(key), label, pos(8 + c * (cw + 5), 4 + r * ch, cw, ch - 4, z),
                         "Dropdown", preset=f"{default}L", single=True))
        z += 1
    vs.append(filled_map(P1, pos(410, 4, 860, 680, z), "My Score",
                         [(mea("County", "My Rank"), "County", "My Rank"),
                          (mea("County", "Weight Used %"), "County", "Weight Used %")])); z += 1
    vs.append(top_bar(P1, pos(1280, 4, 636, 560, z))); z += 1
    vs.append(slicer(P1, "county_filter", "Ozone Status", pos(1280, 570, 310, 114, z), "Basic")); z += 1
    vs.append(slicer(P1, "county_filter", "nox_offset_cost_per_tpy", pos(1600, 570, 316, 114, z), "Between")); z += 1
    vs.append(table_visual(P1, "rank", pos(410, 692, 1506, 384, z), [
        ("c", "County", "county_name"), ("m", "County", "My Score"), ("m", "County", "My Rank"),
        ("m", "County", "Weight Used %"), ("c", "county_filter", "ozone_class"),
        ("c", "county_filter", "nox_offset_cost_per_tpy")], ("m", "County", "My Score", "Descending")))
    write_page(P1, P1, "Score map", vs)

    # ---- page 2: one factor at a time
    vs = []
    vs.append(slicer(P2, "county_factor_score", "factor_label", pos(8, 4, 380, 1070, 1000),
                     "Basic", preset="'Large gas pipe (20 in and up)'", single=True))
    vs.append(card(P2, "title", pos(400, 4, 1516, 80, 1001), mea("County", "Layer Title"), "County", "Layer Title"))
    vs.append(filled_map(P2, pos(400, 90, 900, 986, 1002), "Layer Score",
                         [(mea("County", "Layer Raw Value"), "County", "Layer Raw Value")]))
    vs.append(table_visual(P2, "layer", pos(1310, 90, 606, 986, 1003), [
        ("c", "County", "county_name"), ("m", "County", "Layer Raw Value"),
        ("m", "County", "Layer Score")], ("m", "County", "Layer Score", "Descending")))
    write_page(P2, P2, "Single factor", vs)

    # ---- page 3: county detail (drill-through target)
    vs = []
    vs.append(card(P3, "county", pos(8, 4, 600, 80, 1000), col("County", "county_name"), "County", "county_name"))
    vs.append(table_visual(P3, "factors", pos(8, 90, 700, 986, 1001), [
        ("c", "county_factor_score", "factor_label"), ("c", "county_factor_score", "raw_value"),
        ("c", "county_factor_score", "unit"), ("c", "county_factor_score", "factor_score")],
        ("c", "county_factor_score", "factor_score", "Descending")))
    vs.append(table_visual(P3, "pipes", pos(720, 90, 1196, 500, 1002), [
        ("c", "pipeline_segment", "operator_name"), ("c", "pipeline_segment", "system_name"),
        ("c", "pipeline_segment", "diameter_in"), ("c", "pipeline_segment", "interstate"),
        ("c", "pipeline_segment", "miles")], ("c", "pipeline_segment", "miles", "Descending")))
    vs.append(table_visual(P3, "plants", pos(720, 600, 1196, 476, 1003), [
        ("c", "plant", "plant_name"), ("c", "plant", "technology"),
        ("c", "plant", "nameplate_mw"), ("c", "plant", "operating_year")],
        ("c", "plant", "nameplate_mw", "Descending")))
    fname = hid("drill", "county")
    write_page(P3, P3, "County detail", vs, extra={
        "filterConfig": {"filters": [{"name": fname, "field": col("County", "county_name"),
                                      "type": "Categorical"}]},
        "pageBinding": {"name": hid("bind", "county"), "type": "Drillthrough", "referenceScope": "Default",
                        "parameters": [{"name": hid("param", "county"), "boundFilter": fname,
                                        "fieldExpr": col("County", "county_name")}]}})

    # ---- page 4: catalog
    vs = []
    vs.append(slicer(P4, "metric", "category", pos(8, 4, 300, 400, 1000), "Basic"))
    vs.append(table_visual(P4, "catalog", pos(320, 4, 1596, 1072, 1001), [
        ("c", "metric", "label"), ("c", "metric", "category"), ("c", "metric", "metric_type"),
        ("c", "metric", "unit"), ("c", "metric", "better_direction"), ("c", "metric", "source_name"),
        ("c", "metric", "data_date"), ("c", "metric", "caveat")], ("c", "metric", "category", "Ascending")))
    write_page(P4, P4, "Catalog", vs)


def main():
    global THEME_SRC
    old = OUT / "_theme" / "Fluent2-CY26SU08.json"
    if len(sys.argv) > 1:
        THEME_SRC = Path(sys.argv[1])
    elif old.exists():
        THEME_SRC = old
    OUT.mkdir(exist_ok=True)
    (OUT / f"{NAME}.pbip").write_text(json.dumps({
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2))
    write_model()
    write_report()
    print("wrote", OUT / f"{NAME}.pbip")


if __name__ == "__main__":
    main()
