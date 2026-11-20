"""Public MCP policy and connection settings."""
import os

PUBLIC_PRODUCTS = frozenset({'places', 'acs', 'acs_profile', 'brfss', 'clh', 'cms_gv', 'epa_aqi', 'usda_fea', 'cdc_svi', 'fema_nri'})
FACILITY_PRODUCTS = ('health_centers', 'nursing_homes', 'tri_facilities')
LEVELS = {'state': 2, 'county': 5, 'tract': 11, 'cd': 4}
RULES = (
    'Values are published by the named source for exactly the area shown; CHIP never adds, averages, or derives values across areas.',
    'A missing, suppressed, or not-published value is not zero; read `status_text`.',
    'Each value has its own period, population, and source; do not treat different periods or populations as directly comparable without saying so.',
    'Medicare (cms_gv) measures describe Original Medicare beneficiaries, not all residents.',
    "TRI facilities are facilities that report to EPA's Toxics Release Inventory; reporting does not mean a release, a violation, or a health risk.",
    'Many measures also have earlier published periods. Each value carries its own period, release, and boundary vintage, and an earlier period can differ in method or boundaries (read its `note`). Present values from different periods side by side as published; CHIP does not compute changes or trends.',
    'SVI values are CDC/ATSDR percentile ranks (0–1) among all U.S. counties or all U.S. tracts; do not average, combine, or compare them across years or levels. State-ranked SVI values compare areas only within one state.',
    "NRI scores and percentiles (0–100) and expected annual loss dollars are FEMA's; higher community resilience is better, and higher risk, loss, and social vulnerability are worse; do not average, combine, or re-rank them.",
)
ORDER_WARNING = ('Order is by point estimate. Where uncertainty ranges overlap, the difference may not be meaningful. '
                 'This is a list of one published measure, not a ranking of overall health.')
MAX_BYTES = 50_000
WITHHELD_TOPIC_WARNING = ("The topic 'Health care resources' (HRSA AHRF workforce and hospital measures) "
                          'is on the CHIP website but not available through this public server.')
MAX_ROWS = 400


def allowed_hosts():
    return [item.strip() for item in os.getenv('CHIP_MCP_ALLOWED_HOSTS', '127.0.0.1:*,localhost:*').split(',') if item.strip()]


def public_base_url():
    """Absolute public origin for funding downloads (CHIP_MCP_PUBLIC_BASE_URL)."""
    return os.getenv('CHIP_MCP_PUBLIC_BASE_URL', 'http://127.0.0.1:8011').rstrip('/')
