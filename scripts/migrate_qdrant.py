"""
migrate_qdrant.py — Migra le collection Qdrant da locale a Qdrant Cloud.

Uso:
    python scripts/migrate_qdrant.py \
        --source http://localhost:6333 \
        --target https://xxx.cloud.qdrant.io:6333 \
        --target-key <QDRANT_CLOUD_API_KEY> \
        [--collections geo_texts crops_texts reports_archive]

Installa dipendenze prima:
    pip install qdrant-client tqdm

Come ottenere un cluster Qdrant Cloud gratuito:
    1. Vai su https://cloud.qdrant.io
    2. Crea account gratuito (1 cluster free tier, 1 GB)
    3. Crea un cluster → prendi URL e API key
    4. Aggiorna lavazza-coffee-agent/.env:
         QDRANT_URL=https://xxx.cloud.qdrant.io:6333
         QDRANT_API_KEY=<la-tua-api-key>
"""

import argparse
import sys

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct, VectorParams
    from tqdm import tqdm
except ImportError:
    print("Installa le dipendenze: pip install qdrant-client tqdm")
    sys.exit(1)

COLLECTIONS = ["geo_texts", "crops_texts", "reports_archive"]
BATCH_SIZE = 100


def migrate_collection(src: QdrantClient, dst: QdrantClient, name: str) -> None:
    # Controlla se la collection esiste nella sorgente
    existing = [c.name for c in src.get_collections().collections]
    if name not in existing:
        print(f"  [skip] '{name}' non esiste nella sorgente.")
        return

    info = src.get_collection(name)
    vectors_config = info.config.params.vectors

    # Ricrea la collection nella destinazione
    dst_existing = [c.name for c in dst.get_collections().collections]
    if name in dst_existing:
        print(f"  [warn] '{name}' esiste già nella destinazione — la sovrascrivere.")
        dst.delete_collection(name)

    dst.create_collection(
        collection_name=name,
        vectors_config=vectors_config,
    )

    # Itera e trasferisce in batch
    total = info.points_count or 0
    offset = None
    transferred = 0

    with tqdm(total=total, desc=f"  {name}", unit="pts") as pbar:
        while True:
            records, next_offset = src.scroll(
                collection_name=name,
                limit=BATCH_SIZE,
                offset=offset,
                with_vectors=True,
                with_payload=True,
            )
            if not records:
                break

            points = [
                PointStruct(id=r.id, vector=r.vector, payload=r.payload)
                for r in records
            ]
            dst.upsert(collection_name=name, points=points)

            transferred += len(records)
            pbar.update(len(records))

            if next_offset is None:
                break
            offset = next_offset

    print(f"  ✓ '{name}': {transferred} punti trasferiti.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra Qdrant locale → Qdrant Cloud")
    parser.add_argument("--source", default="http://localhost:6333", help="URL Qdrant sorgente")
    parser.add_argument("--source-key", default=None, help="API key sorgente (se protetta)")
    parser.add_argument("--target", required=True, help="URL Qdrant destinazione (Cloud)")
    parser.add_argument("--target-key", required=True, help="API key Qdrant Cloud")
    parser.add_argument(
        "--collections",
        nargs="+",
        default=COLLECTIONS,
        help=f"Collection da migrare (default: {COLLECTIONS})",
    )
    args = parser.parse_args()

    print(f"\nSorgente : {args.source}")
    print(f"Target   : {args.target}")
    print(f"Collection: {args.collections}\n")

    src = QdrantClient(url=args.source, api_key=args.source_key)
    dst = QdrantClient(url=args.target, api_key=args.target_key)

    for coll in args.collections:
        migrate_collection(src, dst, coll)

    print("\nMigrazione completata.")
    print("Aggiorna ora lavazza-coffee-agent/.env:")
    print(f"  QDRANT_URL={args.target}")
    print(f"  QDRANT_API_KEY={args.target_key}")


if __name__ == "__main__":
    main()
