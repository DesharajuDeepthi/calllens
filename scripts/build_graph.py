"""
CLI to build the Neo4j knowledge graph from Postgres call data.

Usage:
    python scripts/build_graph.py
    python scripts/build_graph.py --tenant-id 00000000-0000-0000-0000-000000000001

Or via Makefile:
    make graph-build
"""

import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from calllens.config import settings
from calllens.graph.builder import build_graph
from calllens.graph.client import close_driver


async def main(tenant_id: str) -> None:
    print(f"Building knowledge graph for tenant {tenant_id} ...")
    print(f"  Postgres : {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
    print(f"  Neo4j    : {settings.neo4j_uri}")

    stats = await build_graph(tenant_id)
    await close_driver()

    print("\nGraph build complete:")
    print(f"  Calls     : {stats['calls']}")
    print(f"  Accounts  : {stats['accounts']}")
    print(f"  Topics    : {stats['topics']}")
    print(f"  Insights  : {stats['insights']}")
    print(f"  INVOLVES  : {stats['involves']}")
    print(f"  COVERS    : {stats['covers']}")
    print(f"  HAS_INSIGHT: {stats['has_insight']}")
    print("\nOpen Neo4j Browser at http://localhost:7474 to explore the graph.")
    print("  MATCH (n) RETURN n LIMIT 50")
    print("  MATCH (a:Account)-[:INVOLVES]-(c:Call)-[:COVERS]->(t:Topic) RETURN a,c,t LIMIT 30")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build CallLens Neo4j knowledge graph")
    parser.add_argument(
        "--tenant-id",
        default=str(settings.default_tenant_id),
        help="Tenant UUID to build graph for",
    )
    args = parser.parse_args()
    asyncio.run(main(args.tenant_id))
