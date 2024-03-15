"""Serialize graphs to/from files on disk."""

import ast
import contextlib
from pathlib import Path
from warnings import warn

import networkx as nx
import pandas as pd
from shapely import wkt

from . import convert
from . import osm_xml
from . import settings
from . import utils


def save_graph_geopackage(G, filepath=None, encoding="utf-8", directed=False):
    """
    Save graph nodes and edges to disk as layers in a GeoPackage file.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        input graph
    filepath : string or pathlib.Path
        path to the GeoPackage file including extension. if None, use default
        data folder + graph.gpkg
    encoding : string
        the character encoding for the saved file
    directed : bool
        if False, save one edge for each undirected edge in the graph but
        retain original oneway and to/from information as edge attributes; if
        True, save one edge for each directed edge in the graph

    Returns
    -------
    None
    """
    # default filepath if none was provided
    filepath = Path(settings.data_folder) / "graph.gpkg" if filepath is None else Path(filepath)

    # if save folder does not already exist, create it
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # convert graph to gdfs and stringify non-numeric columns
    if directed:
        gdf_nodes, gdf_edges = convert.graph_to_gdfs(G)
    else:
        gdf_nodes, gdf_edges = convert.graph_to_gdfs(convert.to_undirected(G))
    gdf_nodes = _stringify_nonnumeric_cols(gdf_nodes)
    gdf_edges = _stringify_nonnumeric_cols(gdf_edges)

    # save the nodes and edges as GeoPackage layers
    gdf_nodes.to_file(filepath, layer="nodes", driver="GPKG", index=True, encoding=encoding)
    gdf_edges.to_file(filepath, layer="edges", driver="GPKG", index=True, encoding=encoding)
    utils.log(f"Saved graph as GeoPackage at {filepath!r}")


def save_graph_shapefile(G, filepath=None, encoding="utf-8", directed=False):
    """
    Do not use: deprecated. Use the save_graph_geopackage function instead.

    The Shapefile format is proprietary and outdated. Instead, use the
    superior GeoPackage file format via the save_graph_geopackage function.
    See http://switchfromshapefile.org/ for more information.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        input graph
    filepath : string or pathlib.Path
        path to the shapefiles folder (no file extension). if None, use
        default data folder + graph_shapefile
    encoding : string
        the character encoding for the saved files
    directed : bool
        if False, save one edge for each undirected edge in the graph but
        retain original oneway and to/from information as edge attributes; if
        True, save one edge for each directed edge in the graph

    Returns
    -------
    None
    """
    warn(
        "The `save_graph_shapefile` function is deprecated and will be removed "
        "in the v2.0.0 release. Instead, use the `save_graph_geopackage` function "
        "to save graphs as GeoPackage files for subsequent GIS analysis. "
        "See the OSMnx v2 migration guide: https://github.com/gboeing/osmnx/issues/1123",
        FutureWarning,
        stacklevel=2,
    )

    # default filepath if none was provided
    filepath = (
        Path(settings.data_folder) / "graph_shapefile" if filepath is None else Path(filepath)
    )

    # if save folder does not already exist, create it (shapefiles
    # get saved as set of files)
    filepath.mkdir(parents=True, exist_ok=True)
    filepath_nodes = filepath / "nodes.shp"
    filepath_edges = filepath / "edges.shp"

    # convert graph to gdfs and stringify non-numeric columns
    if directed:
        gdf_nodes, gdf_edges = convert.graph_to_gdfs(G)
    else:
        gdf_nodes, gdf_edges = convert.graph_to_gdfs(convert.to_undirected(G))
    gdf_nodes = _stringify_nonnumeric_cols(gdf_nodes)
    gdf_edges = _stringify_nonnumeric_cols(gdf_edges)

    # save the nodes and edges as separate ESRI shapefiles
    gdf_nodes.to_file(filepath_nodes, driver="ESRI Shapefile", index=True, encoding=encoding)
    gdf_edges.to_file(filepath_edges, driver="ESRI Shapefile", index=True, encoding=encoding)
    utils.log(f"Saved graph as shapefiles at {filepath!r}")


def save_graphml(G, filepath=None, gephi=False, encoding="utf-8"):
    """
    Save graph to disk as GraphML file.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        input graph
    filepath : string or pathlib.Path
        path to the GraphML file including extension. if None, use default
        data folder + graph.graphml
    gephi : bool
        if True, give each edge a unique key/id to work around Gephi's
        interpretation of the GraphML specification
    encoding : string
        the character encoding for the saved file

    Returns
    -------
    None
    """
    # default filepath if none was provided
    filepath = Path(settings.data_folder) / "graph.graphml" if filepath is None else Path(filepath)

    # if save folder does not already exist, create it
    filepath.parent.mkdir(parents=True, exist_ok=True)

    if gephi:
        # for gephi compatibility, each edge's key must be unique as an id
        uvkd = ((u, v, k, d) for k, (u, v, d) in enumerate(G.edges(keys=False, data=True)))
        G = nx.MultiDiGraph(uvkd)

    else:
        # make a copy to not mutate original graph object caller passed in
        G = G.copy()

    # stringify all the graph attribute values
    for attr, value in G.graph.items():
        G.graph[attr] = str(value)

    # stringify all the node attribute values
    for _, data in G.nodes(data=True):
        for attr, value in data.items():
            data[attr] = str(value)

    # stringify all the edge attribute values
    for _, _, data in G.edges(keys=False, data=True):
        for attr, value in data.items():
            data[attr] = str(value)

    nx.write_graphml(G, path=filepath, encoding=encoding)
    utils.log(f"Saved graph as GraphML file at {filepath!r}")


def load_graphml(
    filepath=None, graphml_str=None, node_dtypes=None, edge_dtypes=None, graph_dtypes=None
):
    """
    Load an OSMnx-saved GraphML file from disk or GraphML string.

    This function converts node, edge, and graph-level attributes (serialized
    as strings) to their appropriate data types. These can be customized as
    needed by passing in dtypes arguments providing types or custom converter
    functions. For example, if you want to convert some attribute's values to
    `bool`, consider using the built-in `ox.io._convert_bool_string` function
    to properly handle "True"/"False" string literals as True/False booleans:
    `ox.load_graphml(fp, node_dtypes={my_attr: ox.io._convert_bool_string})`.

    If you manually configured the `all_oneway=True` setting, you may need to
    manually specify here that edge `oneway` attributes should be type `str`.

    Note that you must pass one and only one of `filepath` or `graphml_str`.
    If passing `graphml_str`, you may need to decode the bytes read from your
    file before converting to string to pass to this function.

    Parameters
    ----------
    filepath : string or pathlib.Path
        path to the GraphML file
    graphml_str : string
        a valid and decoded string representation of a GraphML file's contents
    node_dtypes : dict
        dict of node attribute names:types to convert values' data types. the
        type can be a python type or a custom string converter function.
    edge_dtypes : dict
        dict of edge attribute names:types to convert values' data types. the
        type can be a python type or a custom string converter function.
    graph_dtypes : dict
        dict of graph-level attribute names:types to convert values' data
        types. the type can be a python type or a custom string converter
        function.

    Returns
    -------
    G : networkx.MultiDiGraph
    """
    if (filepath is None and graphml_str is None) or (
        filepath is not None and graphml_str is not None
    ):  # pragma: no cover
        msg = "You must pass one and only one of `filepath` or `graphml_str`."
        raise ValueError(msg)

    # specify default graph/node/edge attribute values' data types
    default_graph_dtypes = {"simplified": _convert_bool_string}
    default_node_dtypes = {
        "elevation": float,
        "elevation_res": float,
        "lat": float,
        "lon": float,
        "osmid": int,
        "street_count": int,
        "x": float,
        "y": float,
    }
    default_edge_dtypes = {
        "bearing": float,
        "grade": float,
        "grade_abs": float,
        "length": float,
        "oneway": _convert_bool_string,
        "osmid": int,
        "reversed": _convert_bool_string,
        "speed_kph": float,
        "travel_time": float,
    }

    # override default graph/node/edge attr types with user-passed types, if any
    if graph_dtypes is not None:
        default_graph_dtypes.update(graph_dtypes)
    if node_dtypes is not None:
        default_node_dtypes.update(node_dtypes)
    if edge_dtypes is not None:
        default_edge_dtypes.update(edge_dtypes)

    if filepath is not None:
        # read the graphml file from disk
        source = filepath
        G = nx.read_graphml(
            Path(filepath), node_type=default_node_dtypes["osmid"], force_multigraph=True
        )
    else:
        # parse the graphml string
        source = "string"
        G = nx.parse_graphml(
            graphml_str, node_type=default_node_dtypes["osmid"], force_multigraph=True
        )

    # convert graph/node/edge attribute data types
    utils.log("Converting node, edge, and graph-level attribute data types")
    G = _convert_graph_attr_types(G, default_graph_dtypes)
    G = _convert_node_attr_types(G, default_node_dtypes)
    G = _convert_edge_attr_types(G, default_edge_dtypes)

    utils.log(f"Loaded graph with {len(G)} nodes and {len(G.edges)} edges from {source!r}")
    return G


def save_graph_xml(
    data,
    filepath=None,
    node_tags=None,
    node_attrs=None,
    edge_tags=None,
    edge_attrs=None,
    oneway=None,
    merge_edges=None,
    edge_tag_aggs=None,
    api_version=None,
    precision=None,
    way_tag_aggs=None,
):
    """
    Save graph to disk as an OSM-formatted XML .osm file.

    This function exists only to allow serialization to the .osm file format
    for applications that require it, and has constraints to conform to that.
    As such, this function has a limited use case which does not include
    saving/loading graphs for subsequent OSMnx analysis. To save/load graphs
    to/from disk for later use in OSMnx, use the `io.save_graphml` and
    `io.load_graphml` functions instead. To load a graph from a .osm file that
    you have downloaded or generated elsewhere, use the `graph.graph_from_xml`
    function.

    Parameters
    ----------
    data : networkx.MultiDiGraph
        the input graph
    filepath : string or pathlib.Path
        do not use, deprecated
    node_tags : list
        do not use, deprecated
    node_attrs: list
        do not use, deprecated
    edge_tags : list
        do not use, deprecated
    edge_attrs : list
        do not use, deprecated
    oneway : bool
        do not use, deprecated
    merge_edges : bool
        do not use, deprecated
    edge_tag_aggs : tuple
        do not use, deprecated
    api_version : float
        do not use, deprecated
    precision : int
        do not use, deprecated
    way_tag_aggs : dict
        Keys are OSM way tag keys and values are aggregation functions
        (anything accepted as an argument by pandas.agg). Allows user to
        aggregate graph edge attribute values into single OSM way values. If
        None, or if some tag's key does not exist in the dict, the way
        attribute will be assigned the value of the first edge of the way.

    Returns
    -------
    None
    """
    osm_xml._save_graph_xml(
        data,
        filepath,
        node_tags,
        node_attrs,
        edge_tags,
        edge_attrs,
        oneway,
        merge_edges,
        edge_tag_aggs,
        api_version,
        precision,
        way_tag_aggs,
    )


def _convert_graph_attr_types(G, dtypes=None):
    """
    Convert graph-level attributes using a dict of data types.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        input graph
    dtypes : dict
        dict of graph-level attribute names:types

    Returns
    -------
    G : networkx.MultiDiGraph
    """
    # remove node_default and edge_default metadata keys if they exist
    G.graph.pop("node_default", None)
    G.graph.pop("edge_default", None)

    for attr in G.graph.keys() & dtypes.keys():
        G.graph[attr] = dtypes[attr](G.graph[attr])

    return G


def _convert_node_attr_types(G, dtypes=None):
    """
    Convert graph nodes' attributes using a dict of data types.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        input graph
    dtypes : dict
        dict of node attribute names:types

    Returns
    -------
    G : networkx.MultiDiGraph
    """
    for _, data in G.nodes(data=True):
        # first, eval stringified lists, dicts, or sets to convert them to objects
        # lists, dicts, or sets would be custom attribute types added by a user
        for attr, value in data.items():
            if (value.startswith("[") and value.endswith("]")) or (
                value.startswith("{") and value.endswith("}")
            ):
                with contextlib.suppress(SyntaxError, ValueError):
                    data[attr] = ast.literal_eval(value)

        for attr in data.keys() & dtypes.keys():
            data[attr] = dtypes[attr](data[attr])
    return G


def _convert_edge_attr_types(G, dtypes=None):
    """
    Convert graph edges' attributes using a dict of data types.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        input graph
    dtypes : dict
        dict of edge attribute names:types

    Returns
    -------
    G : networkx.MultiDiGraph
    """
    # for each edge in the graph, eval attribute value lists and convert types
    for _, _, data in G.edges(data=True, keys=False):
        # remove extraneous "id" attribute added by graphml saving
        data.pop("id", None)

        # first, eval stringified lists, dicts, or sets to convert them to objects
        # edge attributes might have a single value, or a list if simplified
        # dicts or sets would be custom attribute types added by a user
        for attr, value in data.items():
            if (value.startswith("[") and value.endswith("]")) or (
                value.startswith("{") and value.endswith("}")
            ):
                with contextlib.suppress(SyntaxError, ValueError):
                    data[attr] = ast.literal_eval(value)

        # next, convert attribute value types if attribute appears in dtypes
        for attr in data.keys() & dtypes.keys():
            if isinstance(data[attr], list):
                # if it's a list, eval it then convert each item
                data[attr] = [dtypes[attr](item) for item in data[attr]]
            else:
                # otherwise, just convert the single value
                data[attr] = dtypes[attr](data[attr])

        # if "geometry" attr exists, convert its well-known text to LineString
        if "geometry" in data:
            data["geometry"] = wkt.loads(data["geometry"])

    return G


def _convert_bool_string(value):
    """
    Convert a "True" or "False" string literal to corresponding boolean type.

    This is necessary because Python will otherwise parse the string "False"
    to the boolean value True, that is, `bool("False") == True`. This function
    raises a ValueError if a value other than "True" or "False" is passed.

    If the value is already a boolean, this function just returns it, to
    accommodate usage when the value was originally inside a stringified list.

    Parameters
    ----------
    value : string {"True", "False"}
        the value to convert

    Returns
    -------
    bool
    """
    if value in {"True", "False"}:
        return value == "True"

    if isinstance(value, bool):
        return value

    # otherwise the value is not a valid boolean
    msg = f"invalid literal for boolean: {value!r}"
    raise ValueError(msg)


def _stringify_nonnumeric_cols(gdf):
    """
    Make every non-numeric GeoDataFrame column (besides geometry) a string.

    This allows proper serializing via Fiona of GeoDataFrames with mixed types
    such as strings and ints in the same column.

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        gdf to stringify non-numeric columns of

    Returns
    -------
    gdf : geopandas.GeoDataFrame
        gdf with non-numeric columns stringified
    """
    # stringify every non-numeric column other than geometry column
    for col in (c for c in gdf.columns if c != "geometry"):
        if not pd.api.types.is_numeric_dtype(gdf[col]):
            gdf[col] = gdf[col].fillna("").astype(str)

    return gdf
