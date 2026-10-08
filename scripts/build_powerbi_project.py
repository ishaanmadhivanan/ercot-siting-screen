"""Generate the Phase 5 Power BI project (pillar layout) (PBIP: text files instead of one .pbix).

    python scripts/build_powerbi_project.py

Writes powerbi/ercot_siting_v2.pbip plus its .SemanticModel (tables, measures,
weight sliders) and .Report (pages, visuals). Re-running overwrites the files in those
folders, so make report changes either here or, once you start editing in
Power BI Desktop, stop using this script and edit in Desktop.

Why a generator: each of the 5 pillar weight sliders needs a table, a
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

# ---------------------------------------------------------------- pillars
# The county score is built from five pillars (set in dim.metric.pillar).
# Each pillar gets one 0-10 weight slider (default equal). Components inside a
# pillar are switched on/off with the component slicer and count equally.
PILLARS = [
    ("gas", "Gas supply"),
    ("grid", "Grid connection"),
    ("site", "Site control"),
    ("air", "Air permit"),
    ("community", "Community"),
]
PILLAR_DEFAULT = 5
# Every component in the county score (dim.metric rows with a pillar). The component
# list starts with all of these ticked; keep in step with 07_dim_metric.sql.
COMPONENTS = [
    "Gas transmission pipe", "Large gas pipe (20 in and up)", "Interstate gas pipe",
    "Gas pipeline operators", "Gas gathering pipe",
    "Existing generation capacity", "Realised capacity factor", "Gas fleet capacity factor",
    "Generation trend 2020-2024", "Active gas queue", "Active interconnection queue",
    "Gas and coal 40+ years old", "Land in large tracts (100+ ac)",
    "Landowners per 1,000 rural acres", "Parcels of 500+ acres",
    "Ozone nonattainment severity", "Population density",
]
# Kept so wtable()/wmeasure() keep their (key, label, default, lo) shape.
FACTORS = [(k, label, PILLAR_DEFAULT, 0) for k, label in PILLARS]


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
    "string": ("type text", "string", "none"),
    "int": ("Int64.Type", "int64", "none"),
    "num": ("type number", "double", "none"),
    "date": ("type date", "dateTime", "none"),
}

# name -> list of (col, kind, extra) ; SQL is one line on purpose.
TABLES = {
    "County": dict(
        sql="SELECT c.county_fips, c.county_name, c.county_name + ' County, Texas' AS map_label, "
            "c.population, c.land_area_sqmi, "
            "a.ozone_class, a.nox_offset_ratio, a.nox_offset_cost_per_tpy, a.nox_credit_trades, "
            "a.nox_credit_price_per_tpy, a.nox_credit_tons_traded, "
            "a.land_parcel_coverage, a.land_industrial_acres, a.lng_terminal_count, a.lng_terminals, "
            "ISNULL(pp.large_pipe_miles, 0) AS large_pipe_miles "
            "FROM dim.county c LEFT JOIN ("
            "SELECT county_fips, "
            "MAX(CASE WHEN attribute_key = 'ozone_classification' THEN value_text END) AS ozone_class, "
            "MAX(CASE WHEN attribute_key = 'nox_offset_ratio' THEN value_num END) AS nox_offset_ratio, "
            "MAX(CASE WHEN attribute_key = 'nox_offset_cost_per_tpy' THEN value_num END) AS nox_offset_cost_per_tpy, "
            "MAX(CASE WHEN attribute_key = 'nox_credit_trades' THEN value_num END) AS nox_credit_trades, "
            "MAX(CASE WHEN attribute_key = 'land_parcel_coverage' THEN value_num END) AS land_parcel_coverage, "
            "MAX(CASE WHEN attribute_key = 'land_industrial_acres' THEN value_num END) AS land_industrial_acres, "
            "MAX(CASE WHEN attribute_key = 'lng_terminal_count' THEN value_num END) AS lng_terminal_count, "
            "MAX(CASE WHEN attribute_key = 'lng_terminals' THEN value_text END) AS lng_terminals, "
            "MAX(CASE WHEN attribute_key = 'nox_credit_price_per_tpy' THEN value_num END) AS nox_credit_price_per_tpy, "
            "MAX(CASE WHEN attribute_key = 'nox_credit_tons_traded' THEN value_num END) AS nox_credit_tons_traded "
            "FROM fact.county_attribute GROUP BY county_fips) a ON a.county_fips = c.county_fips "
            "LEFT JOIN (SELECT county_fips, SUM(miles) AS large_pipe_miles FROM fact.pipeline_segment "
            "WHERE diameter_in >= 20 GROUP BY county_fips) pp ON pp.county_fips = c.county_fips "
            "WHERE c.in_ercot = 1",
        cols=[("county_fips", "string"), ("county_name", "string"), ("map_label", "string"),
              ("population", "int"), ("land_area_sqmi", "num"), ("ozone_class", "string"),
              ("nox_offset_ratio", "num"), ("nox_offset_cost_per_tpy", "num"),
              ("nox_credit_trades", "num"), ("land_parcel_coverage", "num"),
              ("land_industrial_acres", "num"), ("lng_terminal_count", "num"),
              ("nox_credit_price_per_tpy", "num"), ("nox_credit_tons_traded", "num"),
              ("lng_terminals", "string"), ("large_pipe_miles", "num")],
    ),
    "county_factor_score": dict(
        sql="SELECT county_fips, county_name, factor_key, factor_label, category, pillar, unit, "
            "raw_value, better_direction, score_transform, factor_score FROM rpt.county_factor_score",
        cols=[("county_fips", "string"), ("county_name", "string"), ("factor_key", "string"),
              ("factor_label", "string"), ("category", "string"), ("pillar", "string"), ("unit", "string"),
              ("raw_value", "num"), ("better_direction", "string"), ("score_transform", "string"),
              ("factor_score", "num")],
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
        sql="SELECT metric_key, label, category, pillar, metric_type, unit, better_direction, source_name, "
            "data_date, caveat FROM dim.metric",
        cols=[("metric_key", "string"), ("label", "string"), ("category", "string"), ("pillar", "string"),
              ("metric_type", "string"), ("unit", "string"), ("better_direction", "string"),
              ("source_name", "string"), ("data_date", "date"), ("caveat", "string")],
    ),
}

HIDDEN_COLS = {"county_fips", "factor_key", "score_transform", "better_direction",
               "plant_code", "generator_id", "metric_key", "category", "map_label", "large_pipe_miles"}
FORMATS = {"factor_score": "0", "raw_value": "#,##0.00", "miles": "#,##0.0",
           "nameplate_mw": "#,##0.0", "population": "#,##0", "diameter_in": "0.0",
           "land_area_sqmi": "#,##0.0", "nox_offset_cost_per_tpy": "$#,##0",
           "nox_offset_ratio": "0.0", "land_parcel_coverage": "0%",
           "nox_credit_price_per_tpy": "$#,##0", "nox_credit_tons_traded": "#,##0.0",
           "land_industrial_acres": "#,##0", "large_pipe_miles": "#,##0.0", "lng_terminal_count": "0"}


VIEWS = {"County": "pbi_county", "county_factor_score": "pbi_county_factor_score",
         "pipeline_segment": "pbi_pipeline_segment", "plant": "pbi_plant", "metric": "pbi_metric"}


def m_source(spec, name):
    """Read a named view (sql/03_views/23_vw_powerbi.sql) instead of sending a native
    query: no 'approve this native query' prompts, and the logic stays in SQL."""
    steps = ",".join('{"%s", %s}' % (c, TYPES[k][0]) for c, k in spec["cols"])
    cols = ", ".join('"%s"' % c for c, _ in spec["cols"])
    return [
        "let",
        "\tSource = Sql.Database(ServerName, DatabaseName),",
        '\tView = Source{[Schema = "rpt", Item = "%s"]}[Data],' % VIEWS[name],
        "\tKept = Table.SelectColumns(View, {%s})," % cols,
        "\tTyped = Table.TransformColumnTypes(Kept, {%s})" % steps,
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
        if c in HIDDEN_COLS:
            L.append("\t\tisHidden")
        L.append(f"\t\tsummarizeBy: {'sum' if k in ('num',) and c in ('miles','nameplate_mw') else 'none'}")
        L.append(f"\t\tsourceColumn: {c}")
        L.append("")
    L.append(extra_columns)
    L.append(extra_measures)
    L.append(f"\tpartition {q(name)} = m")
    L.append("\t\tmode: import")
    L.append("\t\tsource =")
    for line in m_source(spec, name):
        L.append("\t\t\t\t" + line)
    L.append("")
    return "\n".join(L) + "\n"


def measure(name, dax, fmt=None, desc=None, hidden=False):
    L = []
    if desc:
        L.append(f"\t/// {desc}")
    L.append(f"\tmeasure {q(name)} = ```")
    for line in dax.strip("\n").split("\n"):
        L.append("\t\t\t" + line)
    L.append("\t\t\t```")
    if fmt:
        L.append(f"\t\tformatString: {fmt}")
    if hidden:
        L.append("\t\tisHidden")
    L.append("")
    return "\n".join(L) + "\n"


PILLAR_PREFIX = "Pillar "


def county_measures():
    switch_lines = ",\n".join(f'        "{label}", [{wmeasure(k)}]' for k, label in PILLARS)
    out = []
    out.append(measure(
        "Weight For Pillar",
        "SWITCH (\n    SELECTEDVALUE ( county_factor_score[pillar] ),\n"
        + switch_lines + ",\n        0\n)",
        "0",
        "Reads the slider for whichever pillar is in the current row. Used by My Score.",
        hidden=True))
    out.append(measure(
        "Pillar Score",
        "AVERAGE ( county_factor_score[factor_score] )",
        "0",
        "Average of the switched-on components that have a value, 0-100. Use with the pillar in the row or axis."))
    out.append(measure(
        "My Score",
        """
VAR p =
    ADDCOLUMNS (
        ALLSELECTED ( county_factor_score[pillar] ),
        "@w", [Weight For Pillar],
        "@s", CALCULATE ( AVERAGE ( county_factor_score[factor_score] ) )
    )
-- A pillar counts only if the county has at least one switched-on component with a
-- value; otherwise it is left out of BOTH the top and the bottom, never counted as 0.
VAR numer = SUMX ( p, IF ( ISBLANK ( [@s] ), 0, [@w] * [@s] ) )
VAR denom = SUMX ( p, IF ( ISBLANK ( [@s] ), 0, [@w] ) )
RETURN
    DIVIDE ( numer, denom )
""", "0", "Pillar scores weighted by the pillar sliders (0-100)."))
    out.append(measure(
        "My Rank",
        "IF ( ISBLANK ( [My Score] ), BLANK (),\n"
        "     RANKX ( ALLSELECTED ( County[county_name] ), [My Score], , DESC, DENSE ) )",
        "0", "1 = best county among those currently shown."))
    out.append(measure(
        "Data coverage %",
        """
VAR p =
    ADDCOLUMNS (
        ALLSELECTED ( county_factor_score[pillar] ),
        "@w", [Weight For Pillar],
        "@s", CALCULATE ( AVERAGE ( county_factor_score[factor_score] ) )
    )
RETURN
    DIVIDE (
        SUMX ( p, IF ( ISBLANK ( [@s] ), 0, [@w] ) ),
        SUMX ( p, [@w] )
    )
""", "0%", "Share of your slider weight the county has data for. Below 100% means a whole pillar was missing and the score is based on the rest."))
    for k, label in PILLARS:
        out.append(measure(
            f"{label} score",
            f'CALCULATE ( AVERAGE ( county_factor_score[factor_score] ), county_factor_score[pillar] = "{label}" )',
            "0", f"{label} pillar score for the county (0-100)."))
    out.append(measure(
        "Layer Score",
        "IF ( HASONEVALUE ( county_factor_score[factor_label] ),\n"
        "     AVERAGE ( county_factor_score[factor_score] ) )",
        "0", "0-100 score for the single factor picked on the Explore one factor page."))
    out.append(measure(
        "Layer Raw Value",
        "IF ( HASONEVALUE ( county_factor_score[factor_label] ),\n"
        "     AVERAGE ( county_factor_score[raw_value] ) )",
        "#,##0.00", "The underlying number before scaling, in the factor's own unit."))
    out.append(measure(
        "Layer Title",
        'SELECTEDVALUE ( county_factor_score[factor_label], "Pick a factor on the left" )'
        '\n    & IF ( HASONEVALUE ( county_factor_score[unit] ), " (" & SELECTEDVALUE ( county_factor_score[unit] ) & ")", "" )'))
    out.append(measure(
        "Detail Title",
        'IF ( HASONEVALUE ( County[county_name] ), SELECTEDVALUE ( County[county_name] ) & " County",\n'
        '     "Right-click a county on the Score map and choose Drill through > County detail" )'))
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
        if name == "County":
            extra_cols = ("\tcolumn 'Ozone Status' = IF ( County[ozone_class] = \"Attainment\", \"Attainment\", \"Nonattainment\" )\n"
                          "\t\tdataType: string\n\t\tsummarizeBy: none\n\n"
                          "\t/// Deal-breaker filter: does the county have any in-service gas transmission line of 20 inches or more?\n"
                          "\tcolumn 'Has 20-inch+ pipeline' = IF ( County[large_pipe_miles] > 0, \"Yes\", \"No\" )\n"
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

    keep = {f"{t}.tmdl" for t in TABLES} | {f"{wtable(k)}.tmdl" for k, *_ in FACTORS}
    for f in (SM / "definition" / "tables").glob("*.tmdl"):
        if f.name not in keep:
            try:
                f.unlink()
            except OSError as e:
                print("could not remove stale", f.name, e)

    rels = [
        ("score_to_county", "county_factor_score.county_fips", "County.county_fips"),
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


def proj(field, entity, prop, active=None, display=None):
    p = {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    if active:
        p["active"] = True
    return p


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def pos(x, y, w, h, z):
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}


def titled(vis, text):
    """Set a visual's title text (otherwise Power BI writes 'X and Y by Z')."""
    vco = vis.setdefault("visualContainerObjects", {})
    vco["title"] = [{"properties": {"show": lit("true"), "text": lit("'" + text.replace("'", "''") + "'")}}]
    vco["subTitle"] = [{"properties": {"show": lit("false")}}]
    return vis


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


def hier_slicer(page, entity, props, position):
    """List slicer over several columns (pillar, then component): multi-select,
    nothing selected = everything on. Filtering county_factor_score rows is what
    switches components off in the score measures."""
    name = hid(page, "hslicer", entity, *props)
    projs = [proj(col(entity, pr), entity, pr, True) for pr in props]
    vis = {"visualType": "slicer",
           "query": {"queryState": {"Values": {"projections": projs}}},
           # isInvertedSelectionMode with no exclusions = "Select all": every box starts
           # ticked and unticking one removes just that component.
           "objects": {"data": [{"properties": {"mode": lit("'Basic'"),
                                                "isInvertedSelectionMode": lit("true")}}],
                       # singleSelect false = tick or untick as many boxes as you like, no Ctrl
                       "selection": [{"properties": {"singleSelect": lit("false"),
                                                     "selectAllCheckboxEnabled": lit("true")}}],
                       "header": [{"properties": {"show": lit("false")}}],
                       "general": [{"properties": {}}]},
           "drillFilterOtherVisuals": True}
    f = [{"name": hid(name, "f", pr), "field": col(entity, pr), "type": "Categorical"} for pr in reversed(props)]
    return name, visual(name, position, vis, f)


def textbox(page, key, position, text, size="12pt", bold=False):
    name = hid(page, "text", key)
    run = {"value": text, "textStyle": {"fontSize": size, **({"fontWeight": "bold"} if bold else {})}}
    vis = {"visualType": "textbox", "drillFilterOtherVisuals": True,
           "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [run]}]}}]}}
    return name, visual(name, position, vis)


def topn_filter(name, n):
    cat = col("County", "county_name")
    return {"name": hid(name, "topn"), "field": cat, "type": "TopN", "filter": {
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


GRADIENT = lambda field: {"solid": {"color": {"expr": {"FillRule": {"Input": field, "FillRule": {
    "linearGradient2": {
        "min": {"color": {"Literal": {"Value": "'#E3EEF9'"}}},
        "max": {"color": {"Literal": {"Value": "'#08519C'"}}},
        "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'specificColor'"}},
                                 "color": {"Literal": {"Value": "'#D9D9D9'"}}}}}}}}}}


def filled_map(page, position, color_measure, tooltips, title=None):
    name = hid(page, "map")
    cat = col("County", "map_label")
    qs = {"Category": {"projections": [proj(cat, "County", "map_label", True)]}}
    if tooltips:
        qs["Tooltips"] = {"projections": [proj(t[0], t[1], t[2], display=(t[3] if len(t) > 3 else None))
                                          for t in tooltips]}
    vis = {"visualType": "filledMap", "query": {"queryState": qs},
           "objects": {"dataPoint": [{"properties": {"fill": GRADIENT(mea("County", color_measure))},
                                      "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]},
           "drillFilterOtherVisuals": True}
    if title:
        titled(vis, title)
    return name, visual(name, position, vis,
                        [{"name": hid(name, "f"), "field": cat, "type": "Categorical"}])


def table_visual(page, key, position, cols, sort, filters=None, title=None):
    """cols: list of (kind, entity, prop[, display name]). sort: (kind, entity, prop, dir)."""
    name = hid(page, "table", key)
    cols = [c if len(c) == 4 else (*c, None) for c in cols]
    fields = [(col if k == "c" else mea)(e, p) for k, e, p, _ in cols]
    projs = [proj(f, e, p, display=d) for f, (k, e, p, d) in zip(fields, cols)]
    sk, se, sp, sd = sort
    vis = {"visualType": "tableEx", "query": {
        "queryState": {"Values": {"projections": projs}},
        "sortDefinition": {"sort": [{"field": (col if sk == "c" else mea)(se, sp), "direction": sd}],
                           "isDefaultSort": True}},
        "objects": {"total": [{"properties": {"totals": lit("false")}}]},
        "drillFilterOtherVisuals": True}
    if title:
        titled(vis, title)
    return name, visual(name, position, vis, filters)


def pillar_bar(page, position):
    """Pillar breakdown. Click a county on the map to see its five pillar scores;
    with nothing selected it shows the average across the counties in view."""
    name = hid(page, "pillarbar")
    cat = col("county_factor_score", "pillar")
    val = mea("County", "Pillar Score")
    vis = {"visualType": "clusteredBarChart", "query": {
        "queryState": {"Category": {"projections": [proj(cat, "county_factor_score", "pillar", True)]},
                       "Y": {"projections": [proj(val, "County", "Pillar Score")]}},
        "sortDefinition": {"sort": [{"field": cat, "direction": "Ascending"}], "isDefaultSort": True}},
        "drillFilterOtherVisuals": False}
    # Clicking a county cross-highlights this chart: the full bar stays as the ERCOT
    # average and the darker part is the selected county.
    titled(vis, "Pillar scores: ERCOT average vs. selected county")
    return name, visual(name, position, vis)


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
    keep = {vname for vname, _ in visuals}
    vroot = p / "visuals"
    if vroot.exists():
        import shutil as _sh
        for old in vroot.iterdir():
            if old.is_dir() and old.name not in keep:
                try:
                    _sh.rmtree(old)
                except OSError as e:
                    print("could not remove stale visual", old.name, e)
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

    # ---- page 1: pillar weights, component switches, map, pillar bar, top 10
    vs, z = [], 1000
    for i, (key, label, default, lo) in enumerate(FACTORS):
        vs.append(slicer(P1, wtable(key), label, pos(8, 4 + i * 74, 395, 70, z),
                         "Dropdown", preset=f"{default}L", single=True))
        z += 1
    vs.append(textbox(P1, "comp", pos(8, 378, 395, 28, z), "Components", "11pt", True)); z += 1
    vs.append(hier_slicer(P1, "county_factor_score", ["pillar", "factor_label"], pos(8, 408, 395, 668, z))); z += 1
    vs.append(filled_map(P1, pos(410, 4, 860, 680, z), "My Score",
                         [(mea("County", "My Score"), "County", "My Score", "Overall score"),
                          (mea("County", "My Rank"), "County", "My Rank", "Rank"),
                          (mea("County", "Data coverage %"), "County", "Data coverage %", "Data coverage")],
                         title="County Rank Visual")); z += 1
    vs.append(pillar_bar(P1, pos(1280, 4, 636, 470, z))); z += 1
    vs.append(slicer(P1, "County", "Ozone Status", pos(1280, 484, 310, 200, z), "Basic")); z += 1
    vs.append(slicer(P1, "County", "Has 20-inch+ pipeline", pos(1600, 484, 316, 200, z), "Basic")); z += 1
    tname, tv = table_visual(P1, "top10", pos(410, 692, 1506, 296, z), [
        ("c", "County", "county_name", "County"), ("m", "County", "My Score", "Overall score")]
        + [("m", "County", f"{label} score", label) for k, label in PILLARS]
        + [("m", "County", "My Rank", "Rank"), ("m", "County", "Data coverage %", "Data coverage")],
        ("m", "County", "My Score", "Descending"), title="Top 10 counties")
    tv["filterConfig"] = {"filters": [topn_filter(tname, 10)]}
    vs.append((tname, tv)); z += 1
    vs.append(textbox(P1, "howto", pos(410, 994, 900, 82, z),
                      "Set how much each pillar matters (0 removes it) and untick any components you don't want. "
                      "Click a county on the map or in the table to zoom in on it. "
                      "For the full breakdown, right-click a county and choose Drill through > County detail.", "11pt")); z += 1
    vs.append(textbox(P1, "asof", pos(1320, 994, 596, 82, z),
                      "Data: EIA 2024 | ERCOT queue Aug 2026 | EPA Green Book Aug 2026 | "
                      "RRC pipelines Sep 2026 | TxGIO parcels 2025", "10pt")); z += 1
    write_page(P1, P1, "Score map", vs)

    # ---- page 2: one factor at a time
    vs = []
    vs.append(slicer(P2, "county_factor_score", "factor_label", pos(8, 4, 380, 1070, 1000),
                     "Basic", preset="'Large gas pipe (20 in and up)'", single=True))
    vs.append(card(P2, "title", pos(400, 4, 1516, 80, 1001), mea("County", "Layer Title"), "County", "Layer Title"))
    vs.append(filled_map(P2, pos(400, 90, 900, 986, 1002), "Layer Score",
                         [(mea("County", "Layer Raw Value"), "County", "Layer Raw Value")],
                         title="Score on this factor (darker = better)"))
    vs.append(table_visual(P2, "layer", pos(1310, 90, 606, 986, 1003), [
        ("c", "County", "county_name", "County"), ("m", "County", "Layer Raw Value", "Value"),
        ("m", "County", "Layer Score", "Score")], ("m", "County", "Layer Score", "Descending")))
    write_page(P2, P2, "Explore one factor", vs)

    # ---- page 3: county detail (drill-through target)
    vs = []
    vs.append(card(P3, "county", pos(8, 4, 1900, 80, 1000), mea("County", "Detail Title"), "County", "Detail Title"))
    vs.append(table_visual(P3, "factors", pos(8, 90, 700, 986, 1001), [
        ("c", "county_factor_score", "pillar", "Pillar"), ("c", "county_factor_score", "factor_label", "Factor"),
        ("c", "county_factor_score", "raw_value", "Value"),
        ("c", "county_factor_score", "unit", "Unit"), ("c", "county_factor_score", "factor_score", "Score")],
        ("c", "county_factor_score", "pillar", "Ascending"), title="Factor scores"))
    vs.append(table_visual(P3, "facts", pos(720, 90, 1196, 160, 1004), [
        ("c", "County", "ozone_class", "Ozone class"),
        ("c", "County", "nox_offset_ratio", "NOx offset ratio"),
        ("c", "County", "nox_offset_cost_per_tpy", "Offset cost ($ per ton/yr emitted)"),
        ("c", "County", "nox_credit_price_per_tpy", "Credit price ($ per ton/yr)"),
        ("c", "County", "nox_credit_tons_traded", "Credits traded, last 2 yrs (tons)"),
        ("c", "County", "lng_terminals", "LNG terminals"),
        ("c", "County", "land_industrial_acres", "Industrial acres"),
        ("c", "County", "land_parcel_coverage", "Parcel data coverage")],
        ("c", "County", "ozone_class", "Ascending"), title="Key facts"))
    vs.append(table_visual(P3, "pipes", pos(720, 260, 1196, 380, 1002), [
        ("c", "pipeline_segment", "operator_name", "Operator"), ("c", "pipeline_segment", "system_name", "System"),
        ("c", "pipeline_segment", "diameter_in", "Diameter (in)"), ("c", "pipeline_segment", "interstate", "Interstate"),
        ("c", "pipeline_segment", "miles", "Miles")], ("c", "pipeline_segment", "miles", "Descending"), title="Gas pipelines"))
    vs.append(table_visual(P3, "plants", pos(720, 650, 1196, 426, 1003), [
        ("c", "plant", "plant_name", "Plant"), ("c", "plant", "technology", "Technology"),
        ("c", "plant", "nameplate_mw", "MW"), ("c", "plant", "operating_year", "Year online")],
        ("c", "plant", "nameplate_mw", "Descending"), title="Operating power plants"))
    fname = hid("drill", "county")
    write_page(P3, P3, "County detail", vs, extra={
        "filterConfig": {"filters": [{"name": fname, "field": col("County", "county_name"),
                                      "type": "Categorical"}]},
        "pageBinding": {"name": hid("bind", "county"), "type": "Drillthrough", "referenceScope": "Default",
                        "parameters": [{"name": hid("param", "county"), "boundFilter": fname,
                                        "fieldExpr": col("County", "county_name")}]}})

    # ---- page 4: catalog
    vs = []
    vs.append(slicer(P4, "metric", "pillar", pos(8, 4, 300, 400, 1000), "Basic"))
    vs.append(table_visual(P4, "catalog", pos(320, 4, 1596, 1072, 1001), [
        ("c", "metric", "pillar", "Pillar"), ("c", "metric", "label", "Metric"), ("c", "metric", "metric_type", "Type"),
        ("c", "metric", "unit", "Unit"), ("c", "metric", "better_direction", "Better when"),
        ("c", "metric", "source_name", "Source"), ("c", "metric", "data_date", "Data as of"),
        ("c", "metric", "caveat", "Notes")], ("c", "metric", "pillar", "Ascending")))
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
