import stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field
    
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

# Fixed packages for each agent with Stripe Product IDs
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

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

# Stripe Checkout Endpoints
@api_router.get("/checkout/status/{session_id}")
async def get_checkout_status(session_id: str):
    try:
        session = stripe.checkout.Session.retrieve(session_id)

        # Update DB if paid
        if session.payment_status == "paid":
            existing = await db.payment_transactions.find_one({"session_id": session_id})

            if existing and existing.get("payment_status") != "paid":
                await db.payment_transactions.update_one(
                    {"session_id": session_id},
                    {
                        "$set": {
                            "payment_status": "paid",
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
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
        webhook_url = f"{host_url}api/webhook/stripe"
        stripe_checkout = StripeCheckout(api_key=stripe_api_key, webhook_url=webhook_url)
        
        # Create checkout session using existing Stripe product
        # Note: Using the product_id approach requires using Stripe SDK directly
        import stripe
        stripe.api_key = stripe_api_key
        
        # Create checkout session with existing product
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product': agent_info["stripe_product_id"],
                    'unit_amount': int(amount * 100),  # Amount in cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "agent_id": request.agent_id,
                "agent_name": agent_info["name"],
                "source": "web_checkout"
            }
        )
        
        # Convert to CheckoutSessionResponse format
        from types import SimpleNamespace
        session_response = SimpleNamespace(
            session_id=session.id,
            url=session.url
        )
        
        # Store transaction in database
        transaction = PaymentTransaction(
            session_id=session_response.session_id,
            agent_id=request.agent_id,
            amount=amount,
            currency="eur",
            payment_status="pending",
            metadata={
                "agent_name": agent_info["name"],
                "source": "web_checkout",
                "stripe_product_id": agent_info["stripe_product_id"]
            }
        )
        
        transaction_doc = transaction.model_dump()
        transaction_doc['created_at'] = transaction_doc['created_at'].isoformat()
        transaction_doc['updated_at'] = transaction_doc['updated_at'].isoformat()
        
        await db.payment_transactions.insert_one(transaction_doc)
        
        logger.info(f"Created checkout session for agent {request.agent_id}: {session_response.session_id}")
        
        return {"url": session_response.url, "session_id": session_response.session_id}
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error creating checkout session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/checkout/status/{session_id}")
async def get_checkout_status(session_id: str):
    try:
        # Initialize Stripe
        stripe_api_key = os.environ.get('STRIPE_API_KEY')
        if not stripe_api_key:
            raise HTTPException(status_code=500, detail="Stripe API key not configured")
        
        stripe_checkout = StripeCheckout(api_key=stripe_api_key, webhook_url="")
        
        # Get status from Stripe
        status_response: CheckoutStatusResponse = await stripe_checkout.get_checkout_status(session_id)
        
        # Update transaction in database if payment is complete
        if status_response.payment_status == "paid":
            existing_transaction = await db.payment_transactions.find_one({"session_id": session_id})
            
            if existing_transaction and existing_transaction.get("payment_status") != "paid":
                await db.payment_transactions.update_one(
                    {"session_id": session_id},
                    {
                        "$set": {
                            "payment_status": "paid",
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
                )
                logger.info(f"Payment completed for session {session_id}")
        
        return {
            "status": status_response.status,
            "payment_status": status_response.payment_status,
            "amount_total": status_response.amount_total,
            "currency": status_response.currency,
            "metadata": status_response.metadata
        }
        
    except Exception as e:
        logger.error(f"Error checking checkout status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    try:
        payload = await request.body()
        sig_header = request.headers.get("Stripe-Signature")
        endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

        if not endpoint_secret:
            raise HTTPException(status_code=500, detail="Webhook secret not configured")

        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]

            await db.payment_transactions.update_one(
                {"session_id": session["id"]},
                {
                    "$set": {
                        "payment_status": session["payment_status"],
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                }
            )

            logger.info(f"Webhook processed for session {session['id']}")

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
