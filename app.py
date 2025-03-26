from flask import Flask, render_template
from elo_calculator import process_historical_data, DatabaseManager
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging

app = Flask(__name__)

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scheduled_update():
    """Run the ELO rating update on schedule"""
    try:
        logger.info("Running scheduled ELO update...")
        process_historical_data(start_year=2018)  # Using our new function
        logger.info("Update complete")
    except Exception as e:
        logger.error(f"Error during scheduled update: {e}")

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(
    scheduled_update,
    'cron',
    day_of_week='mon',
    hour=10,
    misfire_grace_time=3600  # Allow 1 hour for late firing
)
scheduler.start()

@app.route('/')
def index():
    """Main page showing driver ratings"""
    try:
        db = DatabaseManager()
        ratings = db.get_ratings()
        
        if ratings.empty:
            # Initialize with some data if empty
            process_historical_data(start_year=2018)
            ratings = db.get_ratings()
            
        last_updated = db.get_last_update_time()  # You'll need to implement this in DatabaseManager
        db.close()
        
        return render_template(
            'index.html',
            ratings=ratings.to_dict('records'),
            last_updated=last_updated
        )
    except Exception as e:
        logger.error(f"Error loading ratings: {e}")
        return render_template('error.html', error=str(e)), 500

@app.route('/force-update', methods=['POST'])
def force_update():
    """Endpoint for manual updates"""
    try:
        logger.info("Manual update triggered")
        process_historical_data(start_year=2018)
        return {"status": "success", "message": "Ratings updated successfully"}
    except Exception as e:
        logger.error(f"Manual update failed: {e}")
        return {"status": "error", "message": str(e)}, 500

if __name__ == '__main__':
    # Initial data load when starting the server
    try:
        logger.info("Starting initial data load...")
        process_historical_data(start_year=2018)
    except Exception as e:
        logger.error(f"Initial data load failed: {e}")
    
    logger.info("Starting web server...")
    app.run(debug=True)