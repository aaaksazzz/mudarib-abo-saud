from fastapi.responses import HTMLResponse

def register_pages(app):
    routes = {
        "/radar": "static/radar.html",
        "/gold": "static/gold.html",
        "/spot": "static/spot.html",
        "/futures": "static/futures.html",
        "/contracts": "static/contracts.html",
        "/us": "static/us.html",
        "/saudi": "static/saudi.html",
        "/forex": "static/forex.html",
        "/news": "static/news.html",
        "/blog": "static/blog.html",
        "/signup": "static/signup.html",
        "/login": "static/login.html",
        "/admin": "static/admin.html",
    }
    for route, path in routes.items():
        def handler(path=path):
            with open(path, encoding="utf8") as f:
                return HTMLResponse(f.read())
        app.add_api_route(route, handler, methods=["GET"], response_class=HTMLResponse)
