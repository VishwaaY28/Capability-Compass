"""
Seed Neo4j database with initial Vertical and SubVertical data
"""
import logging
from neo4j_graph.services.vertical_service import VerticalService

logger = logging.getLogger(__name__)


# Default verticals and their subverticals
DEFAULT_VERTICALS = {
    "Capital Markets": [
        "Investment banking",
        "Wealth management",
        "Asset management",
        "Private equity",
        "Market infrastructure",
        "Asset services, Custodians",
        "Others",
    ],
    "International Financial Institution (IFI)": [
        "Multilateral Development Bank (MDB)",
        "Development Finance Institution",
        "Nondepository Credit Intermediation",
    ],
    "US Federal Government": [
        "Federal agencies",
    ],
    "Banking": [
        "Retail banking",
        "Investment banking",
        "Corporate banking",
        "Wealth management",
    ],
}


def seed_verticals_and_subverticals():
    """
    Seed Neo4j with default verticals and subverticals.
    
    NOTE: This function is deprecated. Verticals and SubVerticals should be 
    imported from CSV data instead of using static defaults.
    """
    logger.warning("seed_verticals_and_subverticals() is deprecated - use CSV import instead")
    return


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run seeding
    seed_verticals_and_subverticals()
