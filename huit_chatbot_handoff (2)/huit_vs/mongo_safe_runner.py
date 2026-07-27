"""Validate and execute aggregation modules stored in MongoDB safely."""
import copy
import json
import re

ALLOWED_STAGES = {
    "$addFields", "$bucket", "$count", "$facet", "$group", "$limit",
    "$match", "$merge", "$out", "$project", "$replaceRoot", "$set", "$skip",
    "$sort", "$sortByCount", "$unset", "$unwind", "$vectorSearch",
}
FORBIDDEN_OPERATORS = {"$function", "$accumulator", "$where"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,80}$")
PARAM_RE = re.compile(r"^\{\{([A-Z0-9_]+)\}\}$")


class ModuleValidationError(ValueError):
    pass


def _walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _write_targets(pipeline):
    targets = []
    for stage in pipeline:
        if "$out" in stage:
            targets.append(stage["$out"] if isinstance(stage["$out"], str) else stage["$out"].get("coll"))
        if "$merge" in stage:
            target = stage["$merge"].get("into") if isinstance(stage["$merge"], dict) else stage["$merge"]
            targets.append(target.get("coll") if isinstance(target, dict) else target)
    return [target for target in targets if target]


def validate_module(doc):
    if not ID_RE.match(str(doc.get("_id", ""))):
        raise ModuleValidationError("Invalid module id")
    if doc.get("kind") != "mongodb_aggregation":
        raise ModuleValidationError("Unsupported module kind")
    if doc.get("enabled") is not True:
        raise ModuleValidationError("Module is disabled")
    source = doc.get("source_collection")
    if not ID_RE.match(str(source or "")):
        raise ModuleValidationError("Invalid source collection")
    edges = doc.get("private", {}).get("node_function", {}).get("edge", [])
    if len(edges) != 1 or not isinstance(edges[0].get("pipeline"), list):
        raise ModuleValidationError("Exactly one aggregation pipeline is required")
    pipeline = edges[0]["pipeline"]
    if not pipeline or len(pipeline) > 50:
        raise ModuleValidationError("Pipeline length must be 1..50")
    for stage in pipeline:
        if not isinstance(stage, dict) or len(stage) != 1:
            raise ModuleValidationError("Each pipeline stage must have one operator")
        operator = next(iter(stage))
        if operator not in ALLOWED_STAGES:
            raise ModuleValidationError(f"Stage not allowed: {operator}")
        forbidden = FORBIDDEN_OPERATORS.intersection(set(_walk(stage)))
        if forbidden:
            raise ModuleValidationError(f"Forbidden operators: {sorted(forbidden)}")
    targets = _write_targets(pipeline)
    allowed = set(doc.get("allowed_targets", []))
    if targets and doc.get("risk_level") != "write":
        raise ModuleValidationError("Write pipeline must declare risk_level=write")
    if any(target not in allowed for target in targets):
        raise ModuleValidationError("Write target is not allowlisted")
    return {"pipeline": pipeline, "write_targets": targets}


def _substitute(value, params, schema):
    if isinstance(value, str):
        match = PARAM_RE.match(value)
        if match:
            name = match.group(1)
            if name not in params:
                raise ModuleValidationError(f"Missing parameter: {name}")
            expected = schema.get(name, {}).get("type")
            result = params[name]
            if expected == "integer" and not isinstance(result, int):
                raise ModuleValidationError(f"{name} must be integer")
            if expected == "string" and not isinstance(result, str):
                raise ModuleValidationError(f"{name} must be string")
            if expected == "array" and not isinstance(result, list):
                raise ModuleValidationError(f"{name} must be array")
            return result
        return value
    if isinstance(value, list):
        return [_substitute(item, params, schema) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(child, params, schema) for key, child in value.items()}
    return value


def prepare_module(doc, params=None, allow_writes=False):
    checked = validate_module(doc)
    if checked["write_targets"] and not allow_writes:
        raise ModuleValidationError("Write module requires allow_writes=true")
    schema = doc.get("parameters", {}).get("properties", {})
    unknown = set(params or {}) - set(schema)
    if unknown and doc.get("parameters", {}).get("additionalProperties") is False:
        raise ModuleValidationError(f"Unknown parameters: {sorted(unknown)}")
    pipeline = _substitute(copy.deepcopy(checked["pipeline"]), params or {}, schema)
    return {
        "module_id": doc["_id"],
        "source_collection": doc["source_collection"],
        "pipeline": pipeline,
        "risk_level": doc["risk_level"],
        "write_targets": checked["write_targets"],
    }


def run_saved_module(db, module_id, params=None, allow_writes=False, dry_run=True, result_limit=100):
    doc = db["code_modules"].find_one({"_id": module_id})
    if not doc:
        raise ModuleValidationError(f"Module not found: {module_id}")
    prepared = prepare_module(doc, params=params, allow_writes=allow_writes)
    if dry_run:
        return {"dry_run": True, **prepared}
    pipeline = prepared["pipeline"]
    if prepared["risk_level"] == "read":
        pipeline = pipeline + [{"$limit": min(max(int(result_limit), 1), 500)}]
    results = list(db[prepared["source_collection"]].aggregate(pipeline, maxTimeMS=30000))
    return {"dry_run": False, **prepared, "results": results[:result_limit]}
