"""Módulo de estado para el asistente legal."""
import reflex as rx
import asyncio
import logging
from typing import cast

from . import backend_logic as logic

# YA NO SE NECESITA HEREDAR DE NADIE
class AssistantState(rx.State):
    """Gestiona el estado específico del módulo del asistente legal."""

    # --- Propiedades de Estado ---
    thread_id: str | None = None
    messages: list[dict] = []

    # --- Manejadores de Eventos para la UI ---
    
    def set_processing(self, status: bool):
        """Controla el indicador de carga."""
        self.is_processing = status

    def add_file_info(self, file_info: dict):
        """Añade la información de un archivo procesado a la lista en el estado."""
        self.file_info_list.append(file_info)
        self.is_processing = False

    def handle_upload_error(self, error_msg: str):
        """Maneja un error de subida reportado desde el frontend."""
        self.is_processing = False
        logging.error(f"Error de subida (cliente): {error_msg}")

    def delete_file(self, file_id: str):
        """Elimina un archivo de la sesión y de OpenAI."""
        filename = next(
            (f['filename'] for f in self.file_info_list if f['file_id'] == file_id),
            "desconocido"
        )
        if logic.delete_file_from_openai(file_id, filename):
            self.file_info_list = [
                f for f in self.file_info_list if f['file_id'] != file_id
            ]

    async def handle_submit(self, form_data: dict):
        """Gestiona el envío de un mensaje en el chat con OpenAI."""
        prompt = self.user_prompt.strip()
        if not prompt or self.is_processing:
            return

        self.is_processing = True
        self.messages.append({"role": "user", "content": prompt})
        self.user_prompt = ""
        yield

        try:
            if self.thread_id is None:
                thread = await asyncio.to_thread(logic.client.beta.threads.create)
                self.thread_id = thread.id
            
            # (El resto de la lógica de OpenAI va aquí, sin cambios)
            # ...

        except Exception as e:
            logging.error(f"Error en handle_submit: {e}", exc_info=True)
        finally:
            self.is_processing = False
            yield

    async def scrape_leyes(self):
        """Ejecuta el scraping para obtener proyectos de ley recientes."""
        if self.is_scraping:
            return

        self.is_scraping = True
        yield

        df = await asyncio.to_thread(logic.scrape_proyectos_recientes_camara)
        self.proyectos_recientes = df.to_dict(orient="records") if df is not None and not df.empty else []
        self.is_scraping = False

# --- Endpoint de API (definido fuera de la clase) ---
# Esta es la forma correcta de crear un endpoint de API que puede ser añadido a la app.
async def assistant_upload_endpoint(file: rx.UploadFile):
    """Endpoint de API para procesar la subida de archivos."""
    try:
        filename = file.filename
        content_bytes = await file.read()

        if not filename or not content_bytes:
            return {"status": "error", "message": "Archivo inválido."}

        logging.info(f"Endpoint: Procesando '{filename}'.")
        extracted_text = logic.extract_text_from_bytes(filename, content_bytes)
        if not extracted_text:
            return {"status": "error", "message": "No se pudo extraer texto."}

        file_id = logic.upload_text_to_openai(extracted_text, filename)
        if not file_id:
            return {"status": "error", "message": "Fallo al subir a OpenAI."}

        new_file_info = {'file_id': file_id, 'filename': filename}
        return {"status": "success", "file_info": new_file_info}

    except Exception as e:
        logging.error(f"Error crítico en el endpoint de subida: {e}", exc_info=True)
        return {"status": "error", "message": "Error interno del servidor."}