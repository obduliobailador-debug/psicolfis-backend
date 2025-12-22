from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import stripe

app = FastAPI()
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import stripe
from fastapi.middleware.cors import CORSMiddleware

# Crear la aplicación FastAPI
app = FastAPI()

# Habilitar CORS para permitir solicitudes desde el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://psicolfis.net"],  # URL de tu frontend
    allow_credentials=True,
    allow_methods=["*"],  # Permite todos los métodos (GET, POST, etc.)
    allow_headers=["*"],  # Permite todos los encabezados
)

# Configurar la clave secreta de Stripe
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# Definir la estructura de los datos que recibimos en el POST
class CheckoutRequest(BaseModel):
    agent_id: str
    origin_url: str

# Endpoint para crear la sesión de Stripe
@app.post("/api/checkout/session")
async def create_checkout_session(payload: CheckoutRequest):
    """
    Crea una sesión de Stripe Checkout sin usar MongoDB.
    """
    try:
        # Asignamos el nombre del producto según el agente
        nombres = {
            "iris": "PSICOLFIS – IRIS",
            "alex": "PSICOLFIS – ALEX",
            "umbral": "PSICOLFIS – UMBRAL",
        }

        # Si el agente no se encuentra, usamos un valor por defecto
        nombre_producto = nombres.get(payload.agent_id.lower(), "PSICOLFIS – Servicio")

        # Creamos la sesión de pago con Stripe (50€ = 5000 céntimos)
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "eur",
                        "product_data": {"name": nombre_producto},
                        "unit_amount": 5000,  # 50,00 €
                    },
                    "quantity": 1,
                }
            ],
            success_url=f"{payload.origin_url}/gracias?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{payload.origin_url}/cancelado",
        )

        # Devolvemos la URL para redirigir al cliente al pago de Stripe
        return {"url": session.url}

    except Exception as e:
        # Si ocurre un error con Stripe, devolvemos un 500
        raise HTTPException(status_code=500, detail=f"Error creando checkout: {e}")

# Configurar la clave secreta de Stripe
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# Definir la estructura de los datos que recibimos en el POST
class CheckoutRequest(BaseModel):
    agent_id: str
    origin_url: str


# Endpoint para crear la sesión de Stripe
@app.post("/api/checkout/session")
async def create_checkout_session(payload: CheckoutRequest):
    """
    Crea una sesión de Stripe Checkout sin usar MongoDB.
    """
    try:
        # Asignamos el nombre del producto según el agente
        nombres = {
            "iris": "PSICOLFIS – IRIS",
            "alex": "PSICOLFIS – ALEX",
            "umbral": "PSICOLFIS – UMBRAL",
        }

        # Si el agente no se encuentra, usamos un valor por defecto
        nombre_producto = nombres.get(payload.agent_id.lower(), "PSICOLFIS – Servicio")

        # Creamos la sesión de pago con Stripe (50€ = 5000 céntimos)
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "eur",
                        "product_data": {"name": nombre_producto},
                        "unit_amount": 5000,  # 50,00 €
                    },
                    "quantity": 1,
                }
            ],
            success_url=f"{payload.origin_url}/gracias?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{payload.origin_url}/cancelado",
        )

        # Devolvemos la URL para redirigir al cliente al pago de Stripe
        return {"url": session.url}

    except Exception as e:
        # Si ocurre un error con Stripe, devolvemos un 500
        raise HTTPException(status_code=500, detail=f"Error creando checkout: {e}")
