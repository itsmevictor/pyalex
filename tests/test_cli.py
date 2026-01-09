import json
import os
import sys
from unittest.mock import MagicMock, patch, mock_open

import pytest

from pyalex import cli
from pyalex.api import gt_, lt_, not_

# --- Helper Function Tests ---

def test_resolve_api_selection():
    # Test simple mapping
    assert sorted(cli.resolve_api_selection(["title", "doi"])) == sorted(["title", "doi"])
    # Test abstract mapping
    assert "abstract_inverted_index" in cli.resolve_api_selection(["abstract"])
    # Test dot notation (should take root)
    assert "authorships" in cli.resolve_api_selection(["authorships.author.display_name"])
    # Test deduplication
    assert len(cli.resolve_api_selection(["title", "title"])) == 1

def test_parse_filter_value():
    # Basic value
    assert cli.parse_filter_value("123") == ("123", None)
    # Greater than
    val, op = cli.parse_filter_value(">2020")
    assert isinstance(val, gt_)
    assert val.value == "2020"
    assert op is None
    # Less than
    val, op = cli.parse_filter_value("<2020")
    assert isinstance(val, lt_)
    assert val.value == "2020"
    assert op is None
    # Negation
    val, op = cli.parse_filter_value("!journal")
    assert isinstance(val, not_)
    assert val.value == "journal"
    assert op is None
    # OR operator
    val, op = cli.parse_filter_value("a|b|c")
    assert val == ["a", "b", "c"]
    assert op == "or"

def test_prune_data():
    data = {
        "id": "W1",
        "title": "Test Work",
        "publication_year": 2023,
        "authorships": [
            {"author": {"display_name": "Author 1", "id": "A1"}, "raw_affiliation": "Aff 1"},
            {"author": {"display_name": "Author 2", "id": "A2"}, "raw_affiliation": "Aff 2"},
        ]
    }
    
    # Select root fields
    selection = ["id", "title"]
    pruned = cli.prune_data(data, selection)
    assert "id" in pruned
    assert "title" in pruned
    assert "publication_year" not in pruned
    
    # Select nested fields
    selection = ["authorships.author.display_name"]
    pruned = cli.prune_data(data, selection)
    assert "authorships" in pruned
    assert "raw_affiliation" not in pruned["authorships"][0]
    assert "author" in pruned["authorships"][0]
    assert "display_name" in pruned["authorships"][0]["author"]
    assert "id" not in pruned["authorships"][0]["author"]

def test_prune_data_order():
    data = {
        "c": 3,
        "a": 1,
        "b": 2
    }
    selection = ["a", "b", "c"]
    
    # Verify that the output keys follow the selection order
    pruned = cli.prune_data(data, selection)
    assert list(pruned.keys()) == ["a", "b", "c"]

    # Try different order
    selection_reversed = ["c", "b", "a"]
    pruned_reversed = cli.prune_data(data, selection_reversed)
    assert list(pruned_reversed.keys()) == ["c", "b", "a"]

def test_enrich_data():
    # Test abstract inversion
    data = {
        "id": "W1",
        "abstract_inverted_index": {
            "Test": [0], "abstract": [1]
        }
    }
    enriched = cli.enrich_data(data)
    assert enriched["abstract"] == "Test abstract"
    
    # Test list enrichment
    data_list = [data]
    enriched_list = cli.enrich_data(data_list)
    assert enriched_list[0]["abstract"] == "Test abstract"


# --- Config Tests ---

@patch("builtins.open", new_callable=mock_open, read_data='{"email": "test@example.com"}')
@patch("os.path.exists", return_value=True)
def test_load_config(mock_exists, mock_file):
    config = cli.load_config()
    assert config["email"] == "test@example.com"

@patch("builtins.open", new_callable=mock_open)
@patch("pyalex.cli.load_config", return_value={})
def test_save_config(mock_load, mock_file):
    cli.save_config({"api_key": "secret"})
    mock_file.assert_called_with(cli.CONFIG_FILE, "w")
    handle = mock_file()
    # Check that json.dump was called
    # We can inspect the arguments passed to write
    args, _ = handle.write.call_args
    # It writes chunks, but ensuring called is good enough for now, 
    # or we can check json.dump mocking.
    
# --- Command Handler Tests ---

@patch("pyalex.cli.print_json")
@patch("pyalex.cli.load_config")
def test_handle_configure_show(mock_load, mock_print):
    args = MagicMock()
    args.config_action = "show"
    mock_load.return_value = {"email": "test@test.com"}
    
    cli.handle_configure(args)
    mock_print.assert_called_with({"email": "test@test.com"})

@patch("os.remove")
@patch("os.path.exists", return_value=True)
def test_handle_configure_clear(mock_exists, mock_remove):
    args = MagicMock()
    args.config_action = "clear"
    
    cli.handle_configure(args)
    mock_remove.assert_called_with(cli.CONFIG_FILE)

@patch("pyalex.cli.save_config")
def test_handle_configure_set(mock_save):
    args = MagicMock()
    args.config_action = None
    args.set_email = "new@test.com"
    args.set_api_key = None
    
    cli.handle_configure(args)
    mock_save.assert_called_with({"email": "new@test.com"})


@patch("pyalex.cli.print_json")
@patch("pyalex.Works")
def test_handle_get(mock_works_cls, mock_print):
    args = MagicMock()
    args.id = "W1"
    args.select = None
    args.full_record = False
    args.entity = "works"
    
    mock_query = MagicMock()
    mock_works_cls.return_value = mock_query
    mock_query.__getitem__.return_value = {"id": "W1", "title": "Test"}
    
    cli.handle_get(args, mock_works_cls)
    
    mock_query.__getitem__.assert_called_with("W1")
    mock_print.assert_called()

@patch("pyalex.cli.print_json")
@patch("pyalex.Works")
def test_handle_list(mock_works_cls, mock_print):
    args = MagicMock()
    args.search = "query"
    args.filter = ["year:2023"]
    args.select = None
    args.full_record = False
    args.entity = "works"
    args.sort = None
    args.per_page = 25
    
    mock_query = MagicMock()
    mock_works_cls.return_value = mock_query
    mock_query.search.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.get.return_value = [{"id": "W1"}]
    
    cli.handle_list(args, mock_works_cls)
    
    mock_query.search.assert_called_with("query")
    mock_query.get.assert_called_with(per_page=25)
    mock_print.assert_called()

def test_apply_filters():
    mock_query = MagicMock()
    # Mock fluent interface: filter() returns the mock itself
    mock_query.filter.return_value = mock_query
    mock_query.filter_or.return_value = mock_query
    
    filters = ["year:2023", "cited:>10"]
    
    cli.apply_filters(mock_query, filters)
    
    # Check calls
    assert mock_query.filter.call_count == 2
