"""Página del asistente legal."""
import reflex as rx

from ..ui.base import base_page
from .state import AssistantState

# Construimos la URL del endpoint a la que el script de JS llamará.
UPLOAD_ENDPOINT_URL = "/api/assistant/upload"

def assistant_sidebar() -> rx.Component:
    """La barra lateral para subir, gestionar y explorar."""
    return rx.vstack(
        rx.heading("Gestión de Archivos", size="5"),
        rx.upload(
            rx.vstack(
                rx.button("Seleccionar Archivos", color_scheme="gray", variant="soft"),
                rx.text("o arrastra y suelta aquí"),
                rx.cond(
                    AssistantState.is_processing,
                    rx.spinner(padding_top="1em"),
                    rx.fragment(),
                ),
            ),
            id="assistant_uploader",
            border="1px dotted #ccc",
            padding="2em",
            width="100%",
            disabled=AssistantState.is_processing,
            on_drop=rx.call_script(
                f"""
                async (files) => {{
                    const file = files[0];
                    const formData = new FormData();
                    formData.append("file", file);
                    
                    // Activamos el spinner
                    _reflex.event_handlers.setProcessing(true)
                    
                    try {{
                        const response = await fetch('{UPLOAD_ENDPOINT_URL}', {{
                            method: 'POST', body: formData
                        }});
                        const result = await response.json();
                        
                        if (result.status === 'success') {{
                            // Si tiene éxito, llamamos al evento para actualizar la UI
                            _reflex.event_handlers.addFileInfo(result.file_info);
                        }} else {{
                            // Si falla, llamamos al evento de error
                            _reflex.event_handlers.handleUploadError(result.message);
                        }}
                    }} catch (error) {{
                        _reflex.event_handlers.handleUploadError("Error de conexión.");
                    }}
                }}
                """
            ),
        ),
        # ... (resto de la sidebar sin cambios)
    )

# ... (El resto de page.py, como `message_bubble`, `chat_area`, etc. no necesita cambios)