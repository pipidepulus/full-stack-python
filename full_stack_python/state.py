"""El estado principal de la aplicación."""

import reflex as rx
import reflex_local_auth

# Importamos los sub-estados de los diferentes módulos.
from .articles.state import ArticlePublicState
from .assistant.state import AssistantState
from .blog.state import BlogPostState
from .contact.state import ContactState
from .navigation.state import NavState

class State(reflex_local_auth.LocalAuthState):
    """
    El estado principal de la aplicación.
    
    Hereda de LocalAuthState e incluye todos los sub-estados
    de los diferentes módulos de la aplicación.
    """
    
    # Añadimos los sub-estados aquí. Reflex los unirá.
    article_public_state: ArticlePublicState
    assistant_state: AssistantState
    blog_post_state: BlogPostState
    contact_state: ContactState
    nav_state: NavState
    
    def on_load(self):
        """
        Evento que se ejecuta al cargar páginas protegidas para verificar la sesión.
        """
        return self.authenticated_user