"""Punto de entrada principal para la aplicación Reflex."""

import reflex as rx
import reflex_local_auth
from reflex_local_auth.pages import (
    login_page as my_login_page,
    register_page as my_register_page,
)
from .auth.pages import my_logout_page
from rxconfig import config

# --- Importaciones de la Plantilla ---
from .ui.base import base_page
from . import blog, contact, navigation, pages
from .articles.detail import article_detail_page
from .articles.list import article_public_list_page
from .articles.state import ArticlePublicState

# --- Importación de nuestro endpoint del asistente ---
from .assistant.state import assistant_upload_endpoint

# --- ¡IMPORTANTE! Importamos el ESTADO PRINCIPAL desde su propio archivo ---
from .state import State

# --- Página de Inicio ---
def index() -> rx.Component:
    """La página principal."""
    return base_page(
        rx.cond(
            State.is_authenticated,
            pages.dashboard_component(),
            pages.landing_component(),
        )
    )

# --- Creación y Configuración de la App ---
app = rx.App(
    state=State,
    theme=rx.theme(
        appearance="dark",
        has_background=True,
        panel_background="solid",
        scaling="90%",
        radius="medium",
        accent_color="sky"
    )
)

# --- Añadir Páginas de la Aplicación ---

# Página principal
app.add_page(index, on_load=ArticlePublicState.load_posts) # type: ignore

# Páginas de autenticación
app.add_page(my_login_page, route=reflex_local_auth.routes.LOGIN_ROUTE)
app.add_page(my_register_page, route=reflex_local_auth.routes.REGISTER_ROUTE)
app.add_page(my_logout_page, route=navigation.routes.LOGOUT_ROUTE)

# Páginas genéricas de la plantilla
app.add_page(pages.about_page, route=navigation.routes.ABOUT_US_ROUTE)
app.add_page(pages.pricing_page, route=navigation.routes.PRICING_ROUTE)
app.add_page(pages.protected_page, route="/protected/", on_load=State.on_load) # type: ignore

# Páginas de Artículos
app.add_page(
    article_public_list_page,
    route=navigation.routes.ARTICLE_LIST_ROUTE,
    on_load=ArticlePublicState.load_posts # type: ignore
)
app.add_page(
    article_detail_page,
    route=f"{navigation.routes.ARTICLE_LIST_ROUTE}/[post_id]",
    on_load=ArticlePublicState.get_post_detail # type: ignore
)

# Páginas de Blog
app.add_page(
    blog.blog_post_list_page,
    route=navigation.routes.BLOG_POSTS_ROUTE,
    on_load=blog.BlogPostState.load_posts # type: ignore
)
app.add_page(blog.blog_post_add_page, route=navigation.routes.BLOG_POST_ADD_ROUTE)
app.add_page(
    blog.blog_post_detail_page,
    route="/blog/[blog_id]",
    on_load=blog.BlogPostState.get_post_detail # type: ignore
)
app.add_page(
    blog.blog_post_edit_page,
    route="/blog/[blog_id]/edit",
    on_load=blog.BlogPostState.get_post_detail # type: ignore
)

# Páginas de Contacto
app.add_page(contact.contact_page, route=navigation.routes.CONTACT_US_ROUTE)
app.add_page(
    contact.contact_entries_list_page,
    route=navigation.routes.CONTACT_ENTRIES_ROUTE,
    on_load=contact.ContactState.list_entries # type: ignore
)
app.add_page(index, on_load=ArticlePublicState.load_posts) # type: ignore
app.add_page(my_login_page, route=reflex_local_auth.routes.LOGIN_ROUTE)
# ... etc, todas las demás páginas ...
from .assistant.page import assistant_page
app.add_page(assistant_page)


# --- Añadir Rutas de API ---
app.api.add_api_route("/assistant/upload", assistant_upload_endpoint)