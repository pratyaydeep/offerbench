from flask import Flask, render_template, request

from offerbench import db


def _parse_filters(args) -> dict:
    def to_float(name):
        val = args.get(name)
        return float(val) if val else None

    return {
        "role": args.get("role") or None,
        "organization": args.get("organization") or None,
        "location": args.get("location") or None,
        "post_kind": args.get("post_kind") or None,
        "currency": args.get("currency") or None,
        "min_ctc_lakhs": to_float("min_ctc_lakhs"),
        "max_ctc_lakhs": to_float("max_ctc_lakhs"),
        "sort": args.get("sort") or "posted_at_desc",
        "include_no_data": args.get("include_no_data") == "on",
    }


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        filters = _parse_filters(request.args)
        offers = db.query_current_offers(filters)
        return render_template("offers.html", offers=offers, filters=filters)

    @app.route("/offers/rows")
    def offer_rows():
        filters = _parse_filters(request.args)
        offers = db.query_current_offers(filters)
        return render_template("_offer_rows.html", offers=offers)

    @app.route("/offers/<topic_id>")
    def offer_detail(topic_id):
        post, offer = db.get_offer_detail(topic_id)
        return render_template("offer_detail.html", post=post, offer=offer)

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
