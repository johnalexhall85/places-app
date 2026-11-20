"""Streamable HTTP MCP entry point for published CHIP data."""
import gzip
import json
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from app import db as db_module
from app.funding_report import lookup as funding_lookup
from .config import allowed_hosts
from . import tools

INSTRUCTIONS = ("CHIP (Community Health Intelligence Platform, Public Data Observatory) serves published U.S. public-health "
    "and community data for states, counties, census tracts, and 119th Congress districts. Workflow: call find_places "
    "to get GEOIDs, search_measures to get measure keys, then get_area_values (compare up to 25 areas) or "
    "get_measure_across_areas (one measure for every county or district in a state, or tracts in a county). "
    "Use get_measure_details for definitions, get_measure_over_time for published periods of one area and measure, "
    "and get_area_context for related areas and listed facilities. "
    "For across-areas rows, read shared citation and uncertainty kind/label in data.measure. "
    "Cite every number with its `citation`. Report status_text when a value is missing. Do not add, average, "
    "or rank values into composite scores, and say when periods or populations differ. "
    "For CDC NOFO recipient funding, call get_nofo_overview, list_nofo_recipients, or get_recipient_funding; "
    "download the dataset_url from the overview for a full report.")
INSTRUCTIONS += (" For CDC money to recipients in a state, call get_state_funding and list_state_grants; "
                 "for one CDC grant's recipients and history by state, call get_grant_history.")

server = MCPServer(name='CHIP Public Health Data', instructions=INSTRUCTIONS)
annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server.tool(description='Find a state, county, or congressional district GEOID from its name before requesting data. Search counties by name or fips:NNNNN. An empty result suggests trying a FIPS code.', annotations=annotations)(tools.find_places)
server.tool(description='Find public measure keys by words, topic, or area level. Call with no arguments to browse topics. Use get_measure_details for definitions; a missing or suppressed value is never zero.', annotations=annotations)(tools.search_measures)
server.tool(description='Get published definitions, populations, periods, uncertainty, and limitations for measure keys from search_measures. Call this before interpreting comparisons. Unknown keys are reported in warnings.', annotations=annotations)(tools.get_measure_details)
server.tool(description='Get exact published values for up to 25 GEOIDs at one level. First use find_places and search_measures. Read each row status_text: missing, suppressed, and not-published values are not zero.', annotations=annotations)(tools.get_area_values)
server.tool(description='List one published measure across all states, counties or districts in a state, or tracts in a county. Find the measure key and parent GEOID first. Shared citation and uncertainty kind/label are in data.measure. Sorted positions use point estimates; read uncertainty and every missing row.', annotations=annotations)(tools.get_measure_across_areas)
server.tool(description='Show published periods for one measure in one area, oldest first, with period notes and boundary vintages. CHIP computes no change or trend.', annotations=annotations)(tools.get_measure_over_time)
server.tool(description='Get one area boundary context, related areas, and short facility listings without measure values. Find its GEOID first. Facility counts are mapped listings, not access, capacity, or health estimates.', annotations=annotations)(tools.get_area_context)
server.tool(description='List public datasets, active releases, geographic levels, and status meanings before choosing measures. AHRF is excluded. Each measure has one published period, not a time series.', annotations=annotations)(tools.list_data_sources)
server.tool(description='Get a CDC funding opportunity overview, recipient aggregates, source dates, caveats, and an absolute dataset_url for full reports. Amounts carry their sources. Only CDC NOFOs are supported; include_subawards adds a sub-award summary.', annotations=annotations)(tools.get_nofo_overview)
server.tool(description='List compact recipients for one CDC NOFO, in state and name order. Use get_nofo_overview for the dataset_url and source dates when building a full report. Amounts carry their sources; only CDC NOFOs are supported.', annotations=annotations)(tools.list_nofo_recipients)
server.tool(description='Get one CDC NOFO recipient funding profile by UEI, FAIN, award key, or unique name substring. Amounts carry their sources. Get the dataset_url from get_nofo_overview to build a full report.', annotations=annotations)(tools.get_recipient_funding)
server.tool(description='Get CDC state funding totals and budget categories for a fiscal year. Accepts state code, name, or FIPS. Defaults to grants only.', annotations=annotations)(tools.get_state_funding)
server.tool(description='List CDC grant awards in a state with paging, search, and totals over every match. Defaults to grants only.', annotations=annotations)(tools.list_state_grants)
server.tool(description='Get one CDC grant history by fiscal year and state, with paged award histories. Use get_recipient_funding for one full recipient profile.', annotations=annotations)(tools.get_grant_history)

@server.custom_route('/healthz', methods=['GET'])
async def healthz(request):
    return JSONResponse({'ok': True})


_DATASET_CACHE = {}


@server.custom_route('/funding/nofo/{nofo_key}.json', methods=['GET'])
async def nofo_download(request):
    flag = request.query_params.get('subawards', '0')
    if flag not in ('0', '1'):
        return JSONResponse({'error': 'subawards must be 0 or 1'}, status_code=422)
    return await run_in_threadpool(_nofo_download_sync, request.path_params['nofo_key'], flag,
                                   request.headers.get('if-none-match'))


def _nofo_download_sync(nofo_key, flag, if_none_match):
    with db_module.SessionLocal() as session:
        try:
            resolved = funding_lookup.resolve_nofo(session, nofo_key)
            build = funding_lookup.active_build(session)
            key = resolved['nofo_key']
            cache_key = (build['build_id'], key, flag)
            etag = f'"{build["build_id"]}-{key}-{flag}"'
            headers = {'ETag': etag, 'Cache-Control': 'public, max-age=3600'}
            if if_none_match == etag:
                return Response(status_code=304, headers=headers)
            body = _DATASET_CACHE.get(cache_key)
            if body is None:
                data = funding_lookup.nofo_dataset(session, key, flag == '1')
                body = gzip.compress(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), mtime=0)
                _DATASET_CACHE[cache_key] = body
                if len(_DATASET_CACHE) > 24:
                    _DATASET_CACHE.pop(next(iter(_DATASET_CACHE)))
            return Response(body, media_type='application/json', headers={**headers, 'Content-Encoding': 'gzip'})
        except funding_lookup.UnsupportedNOFOError as exc:
            return JSONResponse({'error': str(exc)}, status_code=422)
        except funding_lookup.FundingLookupError as exc:
            return JSONResponse({'error': str(exc)}, status_code=404)

hosts = allowed_hosts()
origins = [f'https://{h}' for h in hosts if '*' not in h] + [f'http://{h}' for h in hosts if '*' not in h]
app = server.streamable_http_app(streamable_http_path='/mcp', json_response=True, stateless_http=True,
                                 transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins))
