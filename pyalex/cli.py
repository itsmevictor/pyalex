import argparse
import json
import sys
import os
import pyalex
from pyalex import config, Works, Authors, Sources, Institutions, Topics, Publishers, Funders, Domains, Fields, Subfields, invert_abstract
from pyalex.api import or_, not_, gt_, lt_

ENTITIES = {
    "works": Works,
    "authors": Authors,
    "sources": Sources,
    "institutions": Institutions,
    "topics": Topics,
    "publishers": Publishers,
    "funders": Funders,
    "domains": Domains,
    "fields": Fields,
    "subfields": Subfields,
}

ENTITY_DOCS = {
    "works": "https://docs.openalex.org/api-entities/works/work-object",
    "authors": "https://docs.openalex.org/api-entities/authors/author-object",
    "sources": "https://docs.openalex.org/api-entities/sources/source-object",
    "institutions": "https://docs.openalex.org/api-entities/institutions/institution-object",
    "topics": "https://docs.openalex.org/api-entities/topics/topic-object",
    "publishers": "https://docs.openalex.org/api-entities/publishers/publisher-object",
    "funders": "https://docs.openalex.org/api-entities/funders/funder-object",
    "domains": "https://docs.openalex.org/api-entities/topics",
    "fields": "https://docs.openalex.org/api-entities/topics",
    "subfields": "https://docs.openalex.org/api-entities/topics",
}

ENTITY_FILTER_DOCS = {
    "works": "https://docs.openalex.org/api-entities/works/filter-works",
    "authors": "https://docs.openalex.org/api-entities/authors/filter-authors",
    "sources": "https://docs.openalex.org/api-entities/sources/filter-sources",
    "institutions": "https://docs.openalex.org/api-entities/institutions/filter-institutions",
    "topics": "https://docs.openalex.org/api-entities/topics/filter-topics",
    "publishers": "https://docs.openalex.org/api-entities/publishers/filter-publishers",
    "funders": "https://docs.openalex.org/api-entities/funders/filter-funders",
}

# Default fields are empty by default (returning full record).
# Users can populate this via configuration.
DEFAULT_FIELDS = {}

CONFIG_FILE = os.path.expanduser("~/.pyalex_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(new_config):
    existing_config = load_config()
    
    # Merge nested dictionaries like default_fields
    if "default_fields" in new_config:
        if "default_fields" not in existing_config:
            existing_config["default_fields"] = {}
        existing_config["default_fields"].update(new_config["default_fields"])
        del new_config["default_fields"]
        
    existing_config.update(new_config)
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(existing_config, f, indent=2)
    print(f"Configuration saved to {CONFIG_FILE}")

def handle_configure(args):
    # Handle subcommands
    if getattr(args, 'config_action', None) == 'show':
        existing_config = load_config()
        if existing_config:
            print_json(existing_config)
        else:
            print("No configuration found.")
        return

    if getattr(args, 'config_action', None) == 'clear':
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
            print(f"Configuration cleared: {CONFIG_FILE}")
        else:
            print("No configuration file to clear.")
        return

    # Handle non-interactive mode (--email or --api-key provided)
    if (hasattr(args, 'set_email') and args.set_email) or (hasattr(args, 'set_api_key') and args.set_api_key):
        new_config = {}
        if hasattr(args, 'set_email') and args.set_email:
            new_config["email"] = args.set_email
        if hasattr(args, 'set_api_key') and args.set_api_key:
            new_config["api_key"] = args.set_api_key
        save_config(new_config)
        return

    # Interactive mode
    print("Configuring PyAlex CLI (press Enter to skip any setting)")

    email = input("Enter your email for the polite pool: ").strip()
    api_key = input("Enter your OpenAlex API key: ").strip()

    new_config = {}
    if email:
        new_config["email"] = email
    if api_key:
        new_config["api_key"] = api_key

    customize = input("Would you like to customize default return fields? (y/N): ").lower().strip()
    if customize == 'y':
        new_config["default_fields"] = {}
        print("\nAvailable entities:", ", ".join(sorted(ENTITIES.keys())))

        while True:
            entity = input("\nEnter entity type to customize (or press Enter to finish): ").strip()
            if not entity:
                break

            if entity not in ENTITIES:
                print(f"Unknown entity '{entity}'. Please choose from the list above.")
                continue

            if entity in DEFAULT_FIELDS:
                current_defaults = ", ".join(DEFAULT_FIELDS[entity])
                print(f"Current defaults for '{entity}': {current_defaults}")
            else:
                print(f"Current defaults for '{entity}': Full record (default)")

            if entity in ENTITY_DOCS:
                print(f"See {ENTITY_DOCS[entity]} for available fields.")

            if entity == "works":
                print("Note: You can also include 'abstract' to get the plaintext abstract.")

            fields_str = input(f"New default fields for '{entity}' (comma-separated): ").strip()
            if fields_str:
                fields = [f.strip() for f in fields_str.split(",") if f.strip()]
                new_config["default_fields"][entity] = fields
                print(f"Updated defaults for '{entity}'.")

    if new_config:
        save_config(new_config)
    else:
        print("No changes made.")

def print_json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

def resolve_api_selection(fields):
    """Map user-facing fields to API fields (e.g., abstract -> abstract_inverted_index, a.b -> a)."""
    if not fields:
        return fields
    
    api_fields = set()
    for f in fields:
        f = f.strip()
        if f == "abstract":
            api_fields.add("abstract_inverted_index")
        else:
            # Add the root field (split by dot and take first part)
            api_fields.add(f.split(".")[0])
    
    return list(api_fields)

def enrich_data(data):
    """Add computed fields like 'abstract' to the data dictionary/object."""
    if isinstance(data, list):
        return [enrich_data(i) for i in data]
    
    if isinstance(data, dict) and data.get("abstract_inverted_index"):
         try:
             data["abstract"] = invert_abstract(data["abstract_inverted_index"])
         except Exception:
             # Fallback if inversion fails for any reason
             data["abstract"] = None
    return data

def prune_data(data, selection):
    """Recursively keep only selected fields, respecting the order of selection."""
    if not selection:
        return data
        
    # Build a tree structure of allowed fields
    # Python 3.7+ dicts preserve insertion order, so iterating selection builds an ordered tree
    tree = {}
    for path in selection:
        parts = path.strip().split('.')
        current = tree
        for part in parts:
            if part not in current:
                current[part] = {}
            current = current[part]
            
    def recursive_prune(obj, allowed_tree):
        # If the node in tree is empty, it means "select this whole field/leaf"
        if not allowed_tree:
             return obj

        if isinstance(obj, dict):
            new_obj = {}
            # Iterate over allowed_tree to preserve selection order
            for key in allowed_tree:
                if key in obj:
                    val = obj[key]
                    new_obj[key] = recursive_prune(val, allowed_tree[key])
            return new_obj
        
        elif isinstance(obj, list):
            return [recursive_prune(item, allowed_tree) for item in obj]
        
        return obj

    if isinstance(data, list):
        return [recursive_prune(item, tree) for item in data]
    else:
        return recursive_prune(data, tree)

def handle_get(args, entity_cls):
    query = entity_cls()
    
    selection = None
    if args.select:
        selection = args.select.split(",")
    elif not args.full_record and args.entity in DEFAULT_FIELDS:
        selection = DEFAULT_FIELDS[args.entity]
    
    if selection:
        query = query.select(resolve_api_selection(selection))

    try:
        result = query[args.id]
        data = enrich_data(result)
        data = prune_data(data, selection)
        print_json(data)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def parse_filter_value(value):
    """Parse a filter value and return (processed_value, operator_type).

    Operators:
    - '>' prefix: greater than
    - '<' prefix: less than
    - '!' prefix: negation
    - '|' separator: OR values
    """
    if not value:
        return value, None

    # Check for OR operator (pipe separator)
    if '|' in value:
        return value.split('|'), 'or'

    # Check for prefix operators
    if value.startswith('>'):
        return gt_(value[1:]), None
    elif value.startswith('<'):
        return lt_(value[1:]), None
    elif value.startswith('!'):
        return not_(value[1:]), None

    return value, None

def parse_key_value(items):
    """Parse list of 'key:value' strings into a dictionary."""
    if not items:
        return {}
    d = {}
    for item in items:
        if ":" not in item:
            d[item] = None
        else:
            key, value = item.split(":", 1)
            d[key] = value
    return d

def apply_filters(query, filter_items):
    """Apply filters to a query, handling logical operators.

    Supports:
    - Basic filters: key:value
    - Greater than: key:>value
    - Less than: key:<value
    - Negation: key:!value
    - OR: key:value1|value2|value3
    """
    if not filter_items:
        return query

    for item in filter_items:
        if ":" not in item:
            continue

        key, value = item.split(":", 1)
        if not value:
            continue

        parsed_value, op_type = parse_filter_value(value)

        if op_type == 'or':
            # Use filter_or for OR values
            query = query.filter_or(**{key: parsed_value})
        else:
            # Regular filter (may include gt_, lt_, not_ wrappers)
            query = query.filter(**{key: parsed_value})

    return query

def handle_list(args, entity_cls):
    query = entity_cls()

    if args.search:
        query = query.search(args.search)

    if args.filter:
        query = apply_filters(query, args.filter)
    
    selection = None
    if args.select:
        selection = args.select.split(",")
    elif not args.full_record and args.entity in DEFAULT_FIELDS:
        selection = DEFAULT_FIELDS[args.entity]
        
    if selection:
        query = query.select(resolve_api_selection(selection))
        
    if args.sort:
        sorts = parse_key_value(args.sort)
        sorts = {k: v for k, v in sorts.items() if v is not None}
        query = query.sort(**sorts)
        
    per_page = args.per_page if args.per_page else 25
    
    try:
        results = query.get(per_page=per_page)
        # Convert results to dicts and enrich
        data = [enrich_data(dict(r)) for r in results]
        data = prune_data(data, selection)
        print_json(data)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def handle_random(args, entity_cls):
    query = entity_cls()
    
    selection = None
    if args.select:
        selection = args.select.split(",")
    elif not args.full_record and args.entity in DEFAULT_FIELDS:
        selection = DEFAULT_FIELDS[args.entity]
        
    if selection:
        query = query.select(resolve_api_selection(selection))

    try:
        result = query.random()
        data = enrich_data(result)
        data = prune_data(data, selection)
        print_json(data)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def handle_sample(args, entity_cls):
    try:
        query = entity_cls()
        if args.filter:
            query = apply_filters(query, args.filter)
        
        selection = None
        if args.select:
             selection = args.select.split(",")
        elif not args.full_record and args.entity in DEFAULT_FIELDS:
             selection = DEFAULT_FIELDS[args.entity]
             
        if selection:
             query = query.select(resolve_api_selection(selection))

        result = query.sample(args.n, seed=args.seed).get()
        data = [enrich_data(dict(r)) for r in result]
        data = prune_data(data, selection)
        print_json(data)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def handle_group_by(args, entity_cls):
    try:
        query = entity_cls()
        if args.filter:
            query = apply_filters(query, args.filter)
             
        if args.search:
            query = query.search(args.search)

        result = query.group_by(args.field).get()
        print_json([dict(r) for r in result])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def handle_autocomplete(args, entity_cls):
    try:
        result = entity_cls().autocomplete(args.q)
        print_json([dict(r) for r in result])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def handle_ngrams(args, entity_cls):
    if entity_cls != Works:
        print("Error: ngrams only available for Works", file=sys.stderr)
        sys.exit(1)
    
    try:
        result = entity_cls()[args.id].ngrams()
        print_json([dict(r) for r in result])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="PyAlex CLI: Python interface to OpenAlex API")
    
    # Global arguments
    parser.add_argument("--email", help="Email for the polite pool")
    parser.add_argument("--api-key", help="OpenAlex API Key")
    
    subparsers = parser.add_subparsers(dest="entity", help="Entity to query or command")

    # Configure command
    config_parser = subparsers.add_parser("configure", help="Configure email, API key and default select fields")
    
    config_subparsers = config_parser.add_subparsers(dest="config_action", help="Configuration actions", required=False)
    
    config_subparsers.add_parser("show", help="Show current configuration")
    config_subparsers.add_parser("clear", help="Clear all configuration")
    
    config_parser.add_argument("--set-email", metavar="EMAIL", help="Set email for the polite pool (non-interactive)")
    config_parser.add_argument("--set-api-key", metavar="KEY", help="Set OpenAlex API key (non-interactive)")
    
    for name, cls in ENTITIES.items():
        entity_parser = subparsers.add_parser(name, help=f"Manage {name}")
        entity_subparsers = entity_parser.add_subparsers(dest="action", required=True)

        select_help = "Comma-separated fields to select. Supports dot notation (e.g. authorships.author.display_name). You can set defaults with 'pyalex configure'."
        if name == "works":
            select_help += " (Use 'abstract' for plaintext abstract)."
        if name in ENTITY_DOCS:
            select_help += f" See {ENTITY_DOCS[name]} for available fields."

        filter_help = "Filters in key:value format. Operators: >value, <value, !value, val1|val2."
        if name in ENTITY_FILTER_DOCS:
            filter_help += f" See {ENTITY_FILTER_DOCS[name]} for available filters."

        # GET command
        get_parser = entity_subparsers.add_parser("get", help=f"Get a single {name[:-1]} by ID")
        get_parser.add_argument("id", help=f"The ID, DOI, or ROR of the {name[:-1]}")
        get_parser.add_argument("--select", help=select_help)
        get_parser.add_argument("--full-record", action="store_true", help="Return the full record (disable default fields)")
        
        # LIST command
        list_parser = entity_subparsers.add_parser("list", help=f"List {name} with filters and search")
        list_parser.add_argument("--search", help="Full-text search query")
        list_parser.add_argument("--filter", action="append", help=filter_help)
        list_parser.add_argument("--select", help=select_help)
        list_parser.add_argument("--full-record", action="store_true", help="Return the full record (disable default fields)")
        list_parser.add_argument("--sort", action="append", help="Sort in key:direction format (e.g. cited_by_count:desc)")
        list_parser.add_argument("--per-page", type=int, default=25, help="Results per page (1-200)")
        
        # RANDOM command
        if name not in ["domains", "fields"]:
            random_parser = entity_subparsers.add_parser("random", help=f"Get a random {name[:-1]}")
            random_parser.add_argument("--select", help=select_help)
            random_parser.add_argument("--full-record", action="store_true", help="Return the full record (disable default fields)")
        
        # SAMPLE command
        sample_parser = entity_subparsers.add_parser("sample", help=f"Get a random sample of {name}")
        sample_parser.add_argument("n", type=int, help="Number of samples")
        sample_parser.add_argument("--seed", type=int, help="Random seed")
        sample_parser.add_argument("--filter", action="append", help=filter_help)
        sample_parser.add_argument("--select", help=select_help)
        sample_parser.add_argument("--full-record", action="store_true", help="Return the full record (disable default fields)")

        # GROUP-BY command
        group_parser = entity_subparsers.add_parser("group-by", help=f"Group {name} by a field")
        group_parser.add_argument("field", help="Field to group by (e.g. publication_year)")
        group_parser.add_argument("--filter", action="append", help=filter_help)
        group_parser.add_argument("--search", help="Search query")

        # AUTOCOMPLETE command
        ac_parser = entity_subparsers.add_parser("autocomplete", help=f"Autocomplete {name}")
        ac_parser.add_argument("q", help="Query string")
        
        # NGRAMS command (Works only)
        if cls == Works:
            ngrams_parser = entity_subparsers.add_parser("ngrams", help="Get n-grams for a work")
            ngrams_parser.add_argument("id", help="Work ID")

    args = parser.parse_args()

    # Load config from file
    file_config = load_config()
    
    # Configure PyAlex
    # Priority is CLI args > Config file > Default
    
    if args.email:
        config.email = args.email
    elif "email" in file_config:
        config.email = file_config["email"]
        
    if args.api_key:
        config.api_key = args.api_key
    elif "api_key" in file_config:
        config.api_key = file_config["api_key"]

    # Update default fields from config
    if "default_fields" in file_config:
        DEFAULT_FIELDS.update(file_config["default_fields"])

    if args.entity == "configure":
        handle_configure(args)
    elif args.entity in ENTITIES:
        cls = ENTITIES[args.entity]
        if args.action == "get":
            handle_get(args, cls)
        elif args.action == "list":
            handle_list(args, cls)
        elif args.action == "random":
            handle_random(args, cls)
        elif args.action == "sample":
            handle_sample(args, cls)
        elif args.action == "group-by":
            handle_group_by(args, cls)
        elif args.action == "autocomplete":
            handle_autocomplete(args, cls)
        elif args.action == "ngrams":
            handle_ngrams(args, cls)
    elif args.entity is None:
        parser.print_help()

if __name__ == "__main__":
    main()