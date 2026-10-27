"""CP2 local PySpark transformations; Spark is optional until CP2 is installed.

This module never launches Spark on import, reads only synthetic run data, and
leaves the Spark session lifecycle to the caller.
"""


def build_transform(spark, input_path: str):
    """Preserve starter entry point; return Spark dataframe for Parquet input."""
    return spark.read.parquet(input_path)


def write_enriched_parquet(spark, records: list[dict], output_path: str,
                           *, single_file: bool = True) -> int:
    """Write typed, partitioned Parquet using an actual Spark DataFrame.

    An empty incremental batch still creates the declared schema and _SUCCESS.
    This function never silently substitutes pandas or PyArrow for Spark.
    """
    from pyspark.sql import types as T
    from pyspark.sql import functions as F

    schema = T.StructType([
        T.StructField("order_id", T.StringType(), False),
        T.StructField("customer_id", T.StringType(), False),
        T.StructField("customer_name", T.StringType(), True),
        T.StructField("amount_usd", T.StringType(), False),
        T.StructField("updated_at_utc", T.StringType(), False),
        T.StructField("ticket_count", T.IntegerType(), False),
        T.StructField("reconciliation_status", T.StringType(), False),
        T.StructField("source_sha256", T.StringType(), False),
        T.StructField("event_date", T.StringType(), False),
    ])
    frame = spark.createDataFrame(records, schema=schema)
    frame = frame.withColumn("amount_usd", F.col("amount_usd").cast(T.DecimalType(18, 2)))
    if frame.filter(F.col("amount_usd").isNull()).limit(1).count():
        raise ValueError("Amount cannot be represented as Decimal(18,2)")
    if frame.filter(~F.col("reconciliation_status").isin("matched", "unmatched_customer")).limit(1).count():
        raise ValueError("Unrecognized reconciliation status")
    if type(single_file) is not bool:
        raise ValueError("single_file must be bool")
    # Opt-in distributed file layout. This does not remove the existing driver
    # input/collect limitation; see CP2 upgrade runbook.
    target = frame.coalesce(1) if single_file else frame.repartition("event_date")
    writer = target.write.mode("errorifexists")
    if records:
        writer.partitionBy("event_date").parquet(output_path)
    else:
        # An empty incremental run must still be readable as a typed dataset.
        writer.parquet(output_path)
    return frame.count()


def spark_joined_records(spark, by_source: dict[str, list[dict]]) -> list[dict]:
    """Perform an actual Spark relational join for ERP / CRM / ticketing.

    Explicit schemas avoid inference ambiguities; collected synthetic rows are
    compared to an independent deterministic reference before publishing.
    """
    from decimal import Decimal
    from pyspark.sql import types as T
    from pyspark.sql import functions as F
    from enterprise_automation.pipelines.incremental_load import parse_timestamp

    order_schema = T.StructType([
        T.StructField("order_id", T.StringType(), False),
        T.StructField("customer_id", T.StringType(), False),
        T.StructField("amount_usd", T.StringType(), False),
        T.StructField("updated_at_utc", T.StringType(), False),
        T.StructField("source_sha256", T.StringType(), False),
    ])
    customer_schema = T.StructType([
        T.StructField("customer_id", T.StringType(), False),
        T.StructField("customer_name", T.StringType(), False),
    ])
    ticket_schema = T.StructType([
        T.StructField("ticket_id", T.StringType(), False),
        T.StructField("customer_id", T.StringType(), False),
    ])
    orders = [{**{k: r["payload"][k] for k in ("order_id", "customer_id", "updated_at_utc")},
               "amount_usd": str(r["payload"]["amount_usd"]),
               "source_sha256": r["record_sha256"]} for r in by_source["ERP"]]
    customers = [{k: r["payload"][k] for k in ("customer_id", "customer_name")}
                 for r in by_source["CRM"]]
    tickets = [{k: r["payload"][k] for k in ("ticket_id", "customer_id")}
               for r in by_source["TICKETING"]]
    o = spark.createDataFrame(orders, order_schema).alias("o")
    c = spark.createDataFrame(customers, customer_schema).alias("c")
    t = spark.createDataFrame(tickets, ticket_schema)
    counts = t.groupBy("customer_id").agg(F.count("ticket_id").cast("int").alias("ticket_count")).alias("t")
    joined = (o.join(c, F.col("o.customer_id") == F.col("c.customer_id"), "left")
              .join(counts, F.col("o.customer_id") == F.col("t.customer_id"), "left"))
    frame = joined.select(
        F.col("o.order_id").alias("order_id"),
        F.col("o.customer_id").alias("customer_id"),
        F.col("c.customer_name").alias("customer_name"),
        F.col("o.amount_usd").cast(T.DecimalType(18, 2)).alias("amount_usd"),
        F.col("o.updated_at_utc").alias("updated_at_utc"),
        F.coalesce(F.col("t.ticket_count"), F.lit(0)).cast("int").alias("ticket_count"),
        F.when(F.col("c.customer_id").isNull(), F.lit("unmatched_customer"))
         .otherwise(F.lit("matched")).alias("reconciliation_status"),
        F.col("o.source_sha256").alias("source_sha256"),
        F.to_date(F.to_timestamp(F.col("o.updated_at_utc"))).cast("string").alias("event_date"),
    )
    results = []
    for row in frame.collect():
        obj = row.asDict()
        if obj["amount_usd"] is None or obj["event_date"] is None:
            raise ValueError("Spark conversion lost amount or event date")
        obj["amount_usd"] = format(Decimal(obj["amount_usd"]), ".2f")
        obj["updated_at_utc"] = parse_timestamp(obj["updated_at_utc"], require_timezone=True).isoformat()
        results.append(obj)
    return sorted(results, key=lambda r: r["order_id"])
