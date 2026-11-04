# Performance

The raw load is tuned for large inputs (hundreds of MB of calendar rows).

## What the load does

- **Vectorized normalization** ([`src/extract/normalize.py`](../src/extract/normalize.py:1)) cleans each chunk with pandas column operations instead of constructing one Pydantic model per row. The field groups it uses are shared with the models, so the two paths cannot drift apart.
- **`COPY ... FROM STDIN`** streams each batch into a temp table that is merged into the raw table with a single `INSERT ... ON CONFLICT`, replacing the per-row upsert.
- **Read/load split**: CSVs are read in `chunk_size` blocks and handed to the loader in `batch_size` slices, so pandas does few large passes while each COPY buffer stays bounded.
- **Connection pooling** keeps one connection alive across batches.
- Set `pipeline.use_copy: false` to fall back to the row-wise `INSERT` path if the database user lacks `COPY` privileges.

## Measured speed-up

Measured on the bundled dataset (8.0M calendar rows, 330 MB of uncompressed CSV) on the author's machine, so treat the figures as orders of magnitude rather than a reproducible benchmark:

| Stage | Before | After | Speed-up |
|-------|--------|-------|----------|
| Normalize + validate (rows/s) | ~176k | ~512k | ~2.9x |
| Load 200k calendar rows | 47.0 s (4.3k rows/s) | 4.5 s (44.2k rows/s) | ~10.4x |

## Related

- [Configuration](configuration.md) for `batch_size`, `chunk_size` and `use_copy`
- [Schema](schema.md) for the layers the load writes into
