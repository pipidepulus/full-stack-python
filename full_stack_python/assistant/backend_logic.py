# pyraglegal_reflex/backend_logic.py

"""
Módulo de lógica de backend para el Asistente Legal.

Este archivo contiene todas las funciones que realizan el trabajo pesado:
- Interacción con la API de OpenAI (cliente, subida/borrado de archivos).
- Procesamiento de archivos (extracción de texto con OCR).
- Scraping web para obtener proyectos de ley.
- Formateo de respuestas y citas.

Estas funciones están diseñadas para ser llamadas desde el estado de Reflex (state.py)
y no contienen ninguna lógica de interfaz de usuario.
"""

import asyncio
import io
import json
import logging
import os
import tempfile
import time
from urllib.parse import urljoin

import docx
import fitz  # PyMuPDF
import openai
import pandas as pd
import pytesseract
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pdf2image import convert_from_path
from PIL import Image

# Cerca del inicio del archivo, junto con tus otras constantes.

INSTRUCCIONES_ASISTENTE = """
## Rol Principal:
Eres un asistente legal ALTAMENTE ESPECIALIZADO EXCLUSIVAMENTE en derecho constitucional colombiano.
Tu misión es ANALIZAR CRÍTICAMENTE documentos legales (leyes o propuestas de ley) A LA LUZ de la Constitución Política de Colombia y el ordenamiento jurídico colombiano.
**NO RESPONDERÁS preguntas que no estén directamente relacionadas con el derecho constitucional colombiano, leyes colombianas, jurisprudencia constitucional colombiana, o el análisis de documentos legales colombianos que el usuario proporcione.**

## Manejo de Consultas Fuera de Especialización:
Si el usuario te hace una pregunta que CLARAMENTE está fuera del ámbito del derecho constitucional colombiano (ej. historia general, ciencia, otros países, etc.), DEBES declinar responderla directamente. En su lugar, responde amablemente indicando tu especialización. Por ejemplo: "Mi especialización es el derecho constitucional colombiano. ¿Tienes alguna consulta relacionada con este tema en la que pueda ayudarte?".

## Fuentes de Información y Metodología:
1.  **Archivos Adjuntos:** Si el mensaje del usuario contiene archivos adjuntos Y la consulta es sobre derecho constitucional colombiano relacionada con ellos, usa `file_search` para basar tu respuesta en ESOS archivos.
2.  **Base de Conocimiento Constitucional:** Para el análisis constitucional, usa tu base de conocimiento (Constitución, leyes, jurisprudencia, doctrina colombiana).

## Estándares para Respuestas:
1.  **Análisis Fundamentado:** Toda conclusión debe derivar del análisis del documento adjunto (si lo hay) y/o de tu base de conocimiento.
2.  **Citación Rigurosa:** Cita con precisión fuentes como Constitución (Art. Z), Ley X (Art. Y), y sentencias (ej. C-XXX/YY, T-XXX/YY, SU-XXX/YY). Usa anotaciones de `file_search` (`【1†fuente】`).
3.  **Formato:** Usa Markdown claro y estructurado.
4.  **Tono:** Profesional, experto, analítico y objetivo.
"""

# --- Configuración Inicial ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
load_dotenv()

# --- Constantes y Cliente OpenAI ---
# Es mejor definir el cliente aquí para que sea reutilizable en todo el módulo.
# Las credenciales y IDs se leen desde las variables de entorno.
ASSISTANT_ID = os.getenv("ASSISTANT_ID_CONSTITUCIONAL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAX_FILES_UPLOAD = 3
SUPPORTED_FILE_TYPES = ["pdf", "txt", "docx"]

if not OPENAI_API_KEY:
    logging.error("CRÍTICO: La variable OPENAI_API_KEY no está configurada.")
    # En una app real, esto debería impedir que se inicie.
    # Reflex manejará los errores si el cliente no se puede crear.
client = openai.OpenAI(api_key=OPENAI_API_KEY)


# --- Bloque de Extracción de Texto (Adaptado para Reflex) ---

def _perform_ocr_on_pdf(file_bytes: bytes, filename: str) -> str:
    """Función auxiliar para realizar OCR en los bytes de un archivo PDF."""
    ocr_text = ""
    # Se necesita un archivo temporal para que pdf2image pueda leerlo desde el disco.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        images = convert_from_path(tmp_path, dpi=200)
        total_pages = len(images)
        for i, image in enumerate(images):
            page_num = i + 1
            logging.info(
                f"Procesando página {page_num}/{total_pages} de '{filename}' con OCR."
            )
            # El estado de Reflex se actualizará externamente para la UI.
            # Esta función solo se encarga de la lógica.
            ocr_text += pytesseract.image_to_string(image, lang='spa+eng') + "\n"
    finally:
        os.remove(tmp_path)  # Limpieza crucial del archivo temporal.
    return ocr_text


def extract_text_from_bytes(filename: str, file_bytes: bytes) -> str | None:
    """
    Extrae texto de un archivo (dado como bytes) para PDF, DOCX, o TXT.

    Args:
        filename: El nombre original del archivo para determinar su tipo.
        file_bytes: El contenido del archivo como un objeto de bytes.

    Returns:
        El texto extraído como una cadena, o None si falla.
    """
    try:
        if filename.lower().endswith('.pdf'):
            logging.info(f"Procesando PDF '{filename}' con PyMuPDF.")
            text = ""
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                for page in doc:
                    text += page.get_text()

            # Si la extracción directa falla o da poco texto, se intenta con OCR.
            if len(text.strip()) < 100:
                logging.warning(
                    f"Texto extraído de '{filename}' es insuficiente. Intentando OCR."
                )
                text = _perform_ocr_on_pdf(file_bytes, filename)
            return text.strip()

        elif filename.lower().endswith('.docx'):
            logging.info(f"Procesando DOCX '{filename}'.")
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n".join([para.text for para in doc.paragraphs]).strip()

        elif filename.lower().endswith('.txt'):
            logging.info(f"Procesando TXT '{filename}'.")
            return file_bytes.decode('utf-8', errors='ignore').strip()

        else:
            logging.error(f"Formato de archivo no soportado: {filename}")
            return None

    except Exception as e:
        logging.error(f"Error al procesar el archivo '{filename}': {e}", exc_info=True)
        return None


# --- Funciones de Interacción con OpenAI ---

def upload_text_to_openai(text_content: str, original_filename: str) -> str | None:
    """
    Crea un archivo de texto temporal y lo sube a OpenAI.

    Args:
        text_content: El contenido de texto a subir.
        original_filename: El nombre del archivo original para logging.

    Returns:
        El ID del archivo de OpenAI si tiene éxito, de lo contrario None.
    """
    # OpenAI necesita un objeto de archivo, por lo que creamos uno temporal.
    name_base = os.path.splitext(original_filename)[0]
    openai_filename = f"{name_base}.txt"

    with tempfile.NamedTemporaryFile(
        mode='w+', delete=False, suffix=".txt", encoding='utf-8'
    ) as tmp_txt:
        tmp_txt.write(text_content)
        tmp_txt_path = tmp_txt.name

    try:
        with open(tmp_txt_path, "rb") as file_obj:
            response = client.files.create(file=file_obj, purpose="assistants")
        logging.info(
            f"Archivo {openai_filename} subido a OpenAI con ID: {response.id}"
        )
        return response.id
    except openai.APIError as e:
        logging.error(f"Error de API al subir archivo {openai_filename}: {e}")
    except Exception as e:
        logging.error(f"Error inesperado al subir archivo {openai_filename}: {e}")
    finally:
        os.remove(tmp_txt_path)  # Limpiar siempre el archivo temporal.
    return None


def delete_file_from_openai(file_id: str, filename_for_log: str) -> bool:
    """Elimina un archivo del almacenamiento de OpenAI por su ID."""
    try:
        logging.info(
            f"Intentando eliminar archivo de OpenAI: {file_id} ({filename_for_log})"
        )
        deleted_file = client.files.delete(file_id)
        logging.info(f"Respuesta de eliminación para {file_id}: {deleted_file}")
        return deleted_file.deleted
    except openai.APIError as e:
        logging.error(f"Error de API al eliminar archivo {file_id}: {e}")
    except Exception as e:
        logging.error(f"Error inesperado al eliminar archivo {file_id}: {e}")
    return False


def process_message_with_citations(message_obj, current_file_info: list) -> str:
    """
    Extrae contenido y anotaciones, formatea citas como notas al pie.

    Args:
        message_obj: El objeto de mensaje de la API de OpenAI.
        current_file_info: La lista de archivos del estado de la app
                           para buscar nombres de archivo.
    """
    try:
        message_content = message_obj.content[0].text
        annotations = message_content.annotations
        citations = []
        processed_text = message_content.value

        for index, annotation in enumerate(annotations):
            processed_text = processed_text.replace(annotation.text, f" [{index + 1}]")

            if file_citation := getattr(annotation, "file_citation", None):
                cited_file_id = file_citation.file_id
                # Busca el nombre del archivo en la lista que ya tenemos en el estado
                file_info = next(
                    (f for f in current_file_info if f["file_id"] == cited_file_id),
                    None,
                )
                filename_display = (
                    file_info['filename'] if file_info else f"ID: {cited_file_id}"
                )
                citations.append(
                    f'[{index + 1}] "{file_citation.quote}" (de {filename_display})'
                )

        if citations:
            return processed_text + "\n\n**Referencias:**\n" + "\n".join(citations)
        return processed_text

    except (AttributeError, IndexError, TypeError) as e:
        logging.error(f"Error procesando citaciones: {e}", exc_info=True)
        # Fallback a devolver el texto plano si la estructura es inesperada
        try:
            return message_obj.content[0].text.value
        except Exception:
            return "(Error al procesar la respuesta del asistente)"


# --- Funciones de Scraping y Herramientas para OpenAI ---

def scrape_proyectos_recientes_camara(num_proyectos=15) -> pd.DataFrame | None:
    """Realiza scraping de proyectos de ley de la Cámara de Representantes."""
    url_camara = "https://www.camara.gov.co/secretaria/proyectos-de-ley#menu"
    base_url_camara = "https://www.camara.gov.co"
    logging.info(f"Scraping: Obteniendo datos de: {url_camara}")
    proyectos_list = []
    try:
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/91.0.4472.124 Safari/537.36'
            )
        }
        response = requests.get(url_camara, timeout=20, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')

        tabla_proyectos = soup.find('table', class_='table')
        if not tabla_proyectos:
            logging.error(f"No se encontró tabla de proyectos en {url_camara}")
            return None

        tbody = tabla_proyectos.find('tbody')
        if not tbody:
            logging.error(f"No se encontró 'tbody' en tabla de proyectos.")
            return None

        filas = tbody.find_all('tr', class_='tablacomispro', limit=num_proyectos)
        for fila in filas:
            celdas = fila.find_all('td')
            if len(celdas) > 2:
                numero = celdas[0].get_text(strip=True)
                titulo_tag = celdas[1].find('a')
                titulo = (
                    titulo_tag.get_text(strip=True)
                    if titulo_tag
                    else celdas[1].get_text(strip=True)
                )
                enlace = (
                    urljoin(base_url_camara, titulo_tag['href'])
                    if titulo_tag and titulo_tag.get('href')
                    else "N/A"
                )
                estado = celdas[2].get_text(strip=True)
                proyectos_list.append({
                    'Número': numero, 'Título': titulo,
                    'Estado': estado, 'Enlace': enlace
                })
        return pd.DataFrame(proyectos_list)

    except requests.exceptions.RequestException as e_req:
        logging.error(f"Error de red durante el scraping: {e_req}")
    except Exception as e_gen:
        logging.error(f"Error inesperado durante el scraping: {e_gen}", exc_info=True)
    return None


def obtener_propuestas_recientes_congreso() -> str:
    """
    Función que será llamada por el Asistente de OpenAI.

    Obtiene propuestas recientes y las formatea como un string JSON.
    """
    logging.info("Función OpenAI: Obteniendo propuestas del congreso...")
    df_data = scrape_proyectos_recientes_camara(num_proyectos=5)

    if df_data is not None and not df_data.empty:
        # Seleccionar solo columnas relevantes para el LLM
        cols = ['Número', 'Título']
        existing_cols = [c for c in cols if c in df_data.columns]
        return json.dumps(
            {"propuestas": df_data[existing_cols].to_dict(orient='records')}
        )
    elif df_data is not None and df_data.empty:
        return json.dumps(
            {"info": "No se encontraron propuestas de ley recientes en la fuente."}
        )
    return json.dumps(
        {"error": "No se pudo obtener la información de propuestas desde la fuente."}
    )

# ... (después de tus otras funciones de OpenAI)

async def get_assistant_response(thread_id, user_prompt, file_ids):
    """
    Gestiona un ciclo completo de interacción con el asistente de OpenAI.
    """
    # 1. Añadir el mensaje del usuario al hilo
    attachments = [{"file_id": fid, "tools": [{"type": "file_search"}]} for fid in file_ids]
    
    await client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_prompt,
        attachments=attachments,
    )

    # 2. Crear el Run con las instrucciones
    run = await client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=ASSISTANT_ID,
        # AQUI ES DONDE VA EL PROMPT
        instructions=INSTRUCCIONES_ASISTENTE,
    )

    # 3. Bucle de sondeo para esperar el resultado
    while run.status in ["queued", "in_progress"]:
        await asyncio.sleep(0.5)
        run = await client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        # Aquí se podría manejar el `requires_action` para las Tools si fuera necesario

    # 4. Procesar y devolver la respuesta
    if run.status == "completed":
        messages = await client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=1)
        # (Aquí llamarías a tu función process_message_with_citations)
        response_text = messages.data[0].content[0].text.value
        return response_text
    else:
        logging.error(f"Run falló con estado: {run.status}. Detalles: {run.last_error}")
        return f"Lo siento, ocurrió un error (Estado: {run.status})."


# Diccionario de herramientas disponibles para el asistente
AVAILABLE_FUNCTIONS = {
    "obtener_propuestas_recientes_congreso": obtener_propuestas_recientes_congreso
}