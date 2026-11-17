"""Streamable HTTP MCP entry point for published CHIP data."""
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from .config import allowed_hosts
from . import tools

INSTRUCTIONS = ("CHIP (Community Health Intelligence Platform, Public Data Observatory) serves published U.S. public-health "
    "and community data for states, counties, census tracts, and 119th Congress districts. Workflow: call find_places "
    "to get GEOIDs, search_measures to get measure keys, then get_area_values (compare up to 25 areas) or "
    "get_measure_across_areas (one measure for every county or district in a state, or tracts in a county). "
    "Use get_measure_details for definitions and get_area_context for related areas and listed facilities. "
    "Cite every number with its `citation`. Report status_text when a value is missing. Do not add, average, "
    "or rank values into composite scores, and say when periods or populations differ.")

server = MCPServer(name='CHIP Public Health Data', instructions=INSTRUCTIONS)
annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server.tool(description='Find a state, county, or congressional district GEOID from its name before requesting data. Search counties by name or fips:NNNNN. An empty result suggests trying a FIPS code.', annotations=annotations)(tools.find_places)
server.tool(description='Find public measure keys by words, topic, or area level. Call with no arguments to browse topics. Use get_measure_details for definitions; a missing or suppressed value is never zero.', annotations=annotations)(tools.search_measures)
server.tool(description='Get published definitions, populations, periods, uncertainty, and limitations for measure keys from search_measures. Call this before interpreting comparisons. Unknown keys are reported in warnings.', annotations=annotations)(tools.get_measure_details)
server.tool(description='Get exact published values for up to 25 GEOIDs at one level. First use find_places and search_measures. Read each row status_text: missing, suppressed, and not-published values are not zero.', annotations=annotations)(tools.get_area_values)
server.tool(description='List one published measure across all states, counties or districts in a state, or tracts in a county. Find the measure key and parent GEOID first. Sorted positions use point estimates; read uncertainty and every missing row.', annotations=annotations)(tools.get_measure_across_areas)
server.tool(description='Get one area boundary context, related areas, and short facility listings without measure values. Find its GEOID first. Facility counts are mapped listings, not access, capacity, or health estimates.', annotations=annotations)(tools.get_area_context)
server.tool(description='List public datasets, active releases, geographic levels, and status meanings before choosing measures. AHRF is excluded. Each measure has one published period, not a time series.', annotations=annotations)(tools.list_data_sources)

@server.custom_route('/healthz', methods=['GET'])
async def healthz(request):
    return JSONResponse({'ok': True})

hosts = allowed_hosts()
origins = [f'https://{h}' for h in hosts if '*' not in h] + [f'http://{h}' for h in hosts if '*' not in h]
app = server.streamable_http_app(streamable_http_path='/mcp', json_response=True, stateless_http=True,
                                 transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins))
