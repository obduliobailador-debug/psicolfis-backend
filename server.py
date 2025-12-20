import stripe
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# FastAPI app and router
app = FastAPI()
api_router = APIRouter(prefix="/api")

# Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

class CheckoutRequest(BaseModel):
    agent_id: str
    origin_url: str

class PaymentTransaction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    agent_id: str
    amount: float
    currency: str
    payment_status: str
    metadata: Dict[str, str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# Agent packages
AGENT_PACKAGES = {
    "iris": {
        "name": "IRIS",
        "price": 50.00,
        "description": "Agente IRIS IA",
        "stripe_product_id": "prod_Tc9fMCQvSB8fbr"
    },
    "alex": {
        "name": "ALEX",
        "price": 50.00,
        "description": "Agente ALEX IA",
        "stripe_product_id": "prod_Tc9lS1WiVy0A2A"
    },
    "umbral": {
        "name": "UMBRAL",
        "price": 50.00,
        "description": "Agente UMBRAL IA",
        "stripe_product_id": "prod_Tc9mIz7zFFxqP8"
    }
}

# Routes
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_obj = StatusCheck(**input.model_dump())
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    results = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for item in results:
        if isinstance(item['timestamp'], str):
            item['timestamp'] = datetime.fromisoformat(item['timestamp'])
    return results

@api_router.post("/checkout/session")
async def create_checkout_session(request: CheckoutRequest):
    try:
        agent_id = request.agent_id.lower()
        if agent_id not in AGENT_PACKAGES:
            raise HTTPException(status_code=400, detail="Invalid agent ID")

        agent = AGENT_PACKAGES[agent_id]
        amount = agent["price"]
        success_url = f"{request.origin_url}/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{request.origin_url}/cancel"

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product': agent["stripe_product_id"],
                    'unit_amount': int(amount * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "agent_id": agent_id,
                "agent_name": agent["name"],
                "source": "web_checkout"
            }
        )

        transaction = PaymentTransaction(
            session_id=session.id,
            agent_id=agent_id,
            amount=amount,
            currency="eur",
            payment_status="pending",
            metadata={
                "agent_name": agent["name"],
                "source": "web_checkout",
                "stripe_product_id": agent["stripe_product_id"]
            }
        )
        doc = transaction.model_dump()
        doc['created_at'] = doc['created_at'].isoformat()
        doc['updated_at'] = doc['updated_at'].isoformat()
        await db.payment_transactions.insert_one(doc)

        return {"url": session.url, "session_id": session.id}

    except Exception as e:
        logger.error(f"Error creating checkout session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/checkout/status/{session_id}")
async def get_checkout_status(session_id: str):
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == "paid":
            existing = await db.payment_transactions.find_one({"session_id": session_id})
            if existing and existing.get("payment_status") != "paid":
                await db.payment_transactions.update_one(
                    {"session_id": session_id},
                    {"$set": {
                        "payment_status": "paid",
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
        return {
            "status": session.status,
            "payment_status": session.payment_status,
            "amount_total": session.amount_total,
            "currency": session.currency,
            "metadata": session.metadata
        }
    except Exception as e:
        logger.error(f"Error checking payment status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    try:
        payload = await request.body()
        sig_header = request.headers.get("Stripe-Signature")
        endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

        if not endpoint_secret:
            raise HTTPException(status_code=500, detail="Webhook secret not configured")

        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            await db.payment_transactions.update_one(
                {"session_id": session["id"]},
                {"$set": {
                    "payment_status": session["payment_status"],
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            logger.info(f"Webhook processed for session {session['id']}")

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

# Middleware and shutdown
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
