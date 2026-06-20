import logging

import click

from offerbench import db, extract, ingest


@click.group()
@click.option("-q", "--quiet", is_flag=True, help="Suppress per-item progress logs")
def cli(quiet):
    logging.basicConfig(
        level=logging.WARNING if quiet else logging.INFO,
        format="%(message)s",
    )


@cli.command()
@click.option("--page-size", default=50, show_default=True, help="Posts per list page")
@click.option("--delay", default=1.0, show_default=True, help="Seconds between list pages")
@click.option("--limit", default=None, type=int, help="Cap the number of new posts fetched (for testing)")
@click.option("--batch-size", default=10, show_default=True, help="Detail fetches per batch")
@click.option("--batch-delay", default=5.0, show_default=True, help="Seconds to pause between detail-fetch batches")
def sync(page_size, delay, limit, batch_size, batch_delay):
    """Fetch new posts (and any missing detail content). Walks the full list
    every run, filling in any historical gaps, not just the newest posts."""
    result = ingest.sync_new_posts(
        page_size=page_size,
        request_delay_s=delay,
        limit=limit,
        batch_size=batch_size,
        batch_delay_s=batch_delay,
    )
    click.echo(f"New posts: {result.new_posts}, detail fetched: {result.detail_fetched}")


@cli.command(name="extract")
@click.option("--force", is_flag=True, help="Re-extract posts already extracted at the current version")
@click.option("--limit", default=None, type=int, help="Cap the number of posts processed")
@click.option("--batch-size", default=10, show_default=True, help="LLM calls per batch")
@click.option("--batch-delay", default=5.0, show_default=True, help="Seconds to pause between batches")
def extract_cmd(force, limit, batch_size, batch_delay):
    """Run LLM extraction on posts pending extraction."""
    result = extract.extract_pending(
        force=force, limit=limit, batch_size=batch_size, batch_delay_s=batch_delay
    )
    click.echo(
        f"Processed: {result.processed} | ok: {result.ok} | "
        f"low_confidence: {result.low_confidence} | no_data: {result.no_data} | "
        f"errors: {result.errors}"
    )


@cli.command()
def status():
    """Show pipeline counts."""
    counts = db.status_counts()
    click.echo(f"Raw posts: {counts['raw_posts']}")
    click.echo(f"Missing detail content: {counts['missing_detail']}")
    click.echo(f"Extracted (current version): {counts['extracted_total']}")
    for k, v in counts["by_status"].items():
        click.echo(f"  {k}: {v}")


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=5000, show_default=True)
@click.option("--debug", is_flag=True)
def serve(host, port, debug):
    """Run the local web dashboard."""
    from offerbench.web.app import create_app

    create_app().run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    cli()
