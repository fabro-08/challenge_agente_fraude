"""Router de usuarios del equipo de fraude."""

from fastapi import APIRouter

from src.api import schemas
from src.rules import repository

router = APIRouter()


@router.get("/users", response_model=list[schemas.UserOut])
def list_users():
    """Lista los analistas de fraude activos (selector UI)."""
    conn = repository._conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT usuario_id, nombre, email FROM usuarios_fraude WHERE activo ORDER BY nombre"
            )
            cols = [desc[0] for desc in cur.description]
            return [schemas.UserOut(**dict(zip(cols, r))) for r in cur.fetchall()]
    finally:
        conn.close()
