import fastf1
import pandas as pd
import numpy as np
import traceback
import requests
import sqlite3
from datetime import datetime
from typing import Optional

fastf1.Cache.disabled()  

class F1EloRating:
    def __init__(self, initial_rating: float = 1500, k_factor: float = 24):
        self.ratings = {}
        self.initial_rating = initial_rating
        self.k_factor = k_factor
        
    def update_ratings(self, race_results: pd.DataFrame):
        race_results = race_results.dropna(subset=['Driver', 'Position'])
        
        if len(race_results) < 2:
            print("Not enough valid drivers to calculate ratings")
            return
        
        # Initialize new drivers
        for driver in race_results['Driver'].unique():
            if driver not in self.ratings:
                self.ratings[driver] = self.initial_rating
        
        total_drivers = len(race_results)
        
        # Process each driver's result
        for _, row in race_results.iterrows():
            driver = row['Driver']
            position = int(row['Position'])
            
            opponents = race_results[race_results['Driver'] != driver]
            actual_score = 1 - (position - 1) / (total_drivers - 1)  # Normalized score
            
            # Calculate expected score against all opponents
            expected_score = np.mean([
                1 / (1 + 10 ** ((self.ratings[opp] - self.ratings[driver]) / 400))
                for opp in opponents['Driver']
            ])
            
            # Update rating
            self.ratings[driver] += self.k_factor * (actual_score - expected_score)
    
    def get_driver_ratings(self) -> pd.DataFrame:
        return pd.DataFrame.from_dict(self.ratings, orient='index', columns=['Elo Rating'])\
                         .sort_values('Elo Rating', ascending=False)

class F1DataCollector:
    def __init__(self, start_year: int = 2014):
        self.start_year = start_year
        self.current_year = datetime.now().year
    
    def get_all_historical_data(self) -> pd.DataFrame:
        all_results = pd.DataFrame()
        
        for year in range(self.start_year, self.current_year + 1):
            print(f"\nProcessing year {year}...")
            year_results = self._process_year(year)
            if not year_results.empty:
                all_results = pd.concat([all_results, year_results])
        
        return all_results
    
    def _process_year(self, year: int) -> pd.DataFrame:
        try:
            if year >= 2018:
                schedule = fastf1.get_event_schedule(year)
            else:
                url = f"http://ergast.com/api/f1/{year}.json"
                response = requests.get(url)
                schedule = response.json()['MRData']['RaceTable']['Races']
            
            all_races = pd.DataFrame()
            
            for race_num in range(1, len(schedule) + 1):
                print(f"  Processing race {race_num}...", end=' ')
                race_results = self.collect_race_results(year, race_num)
                if not race_results.empty:
                    race_results['Year'] = year
                    race_results['RaceNumber'] = race_num
                    all_races = pd.concat([all_races, race_results])
                    print("✓")
                else:
                    print("×")
            
            return all_races
        
        except Exception as e:
            print(f"Error processing year {year}: {e}")
            traceback.print_exc()
            return pd.DataFrame()
    
    def collect_race_results(self, year: int, race_number: int) -> pd.DataFrame:
        if year >= 2018:
            return self._collect_with_fastf1(year, race_number)
        return self._collect_with_ergast(year, race_number)
    
    def _collect_with_fastf1(self, year: int, race_number: int) -> pd.DataFrame:
        try:
            session = fastf1.get_session(year, race_number, 'R')
            session.load(telemetry=False, weather=False)  # Faster loading
            results = session.results
            
            driver_column = next((col for col in ['FullName', 'Driver', 'driver'] 
                               if col in results.columns), None)
            if not driver_column:
                return pd.DataFrame()
            
            return pd.DataFrame({
                'Driver': results[driver_column],
                'Position': pd.to_numeric(results['Position'], errors='coerce')
            }).dropna()
        
        except Exception as e:
            print(f"FastF1 error: {e}")
            return pd.DataFrame()
    
    def _collect_with_ergast(self, year: int, race_number: int) -> pd.DataFrame:
        try:
            url = f"http://ergast.com/api/f1/{year}/{race_number}/results.json"
            data = requests.get(url).json()
            
            if not data['MRData']['RaceTable']['Races']:
                return pd.DataFrame()
            
            results = []
            for result in data['MRData']['RaceTable']['Races'][0]['Results']:
                try:
                    results.append({
                        'Driver': f"{result['Driver']['givenName']} {result['Driver']['familyName']}",
                        'Position': int(result['position'])
                    })
                except (KeyError, ValueError):
                    continue
            
            return pd.DataFrame(results)
        
        except Exception as e:
            print(f"Ergast error: {e}")
            return pd.DataFrame()

class DatabaseManager:
    def __init__(self, db_name='f1_elo.db'):
        self.conn = sqlite3.connect(db_name)
        self._init_db()
    
    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS driver_ratings (
                driver_name TEXT PRIMARY KEY,
                elo_rating REAL,
                last_updated TEXT
            )
        ''')
        self.conn.commit()
    
    def save_ratings(self, ratings_df: pd.DataFrame):
        cursor = self.conn.cursor()
        current_time = datetime.now().isoformat()
        
        for driver, row in ratings_df.iterrows():
            cursor.execute('''
                INSERT OR REPLACE INTO driver_ratings (driver_name, elo_rating, last_updated)
                VALUES (?, ?, ?)
            ''', (driver, row['Elo Rating'], current_time))
        
        self.conn.commit()
    
    def get_ratings(self) -> pd.DataFrame:
        cursor = self.conn.cursor()
        cursor.execute('SELECT driver_name, elo_rating FROM driver_ratings ORDER BY elo_rating DESC')
        rows = cursor.fetchall()
        return pd.DataFrame(rows, columns=['Driver', 'Elo Rating']) if rows else pd.DataFrame()
    
    def close(self):
        self.conn.close()

    def get_last_update_time(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT MAX(last_updated) FROM driver_ratings')
        result = cursor.fetchone()
        return result[0] if result else "Never"

def process_historical_data(start_year: int = 2014):
    print("Starting historical data processing...")
    collector = F1DataCollector(start_year)
    elo = F1EloRating()
    db = DatabaseManager()
    
    # Load existing ratings if any
    existing_ratings = db.get_ratings()
    if not existing_ratings.empty:
        elo.ratings = existing_ratings.set_index('Driver')['Elo Rating'].to_dict()
    
    # Get all historical race results
    all_races = collector.get_all_historical_data()
    
    if not all_races.empty:
        # Process races in chronological order
        for (year, race_num), race_group in all_races.groupby(['Year', 'RaceNumber']):
            print(f"\nProcessing {year} Race {race_num}...")
            elo.update_ratings(race_group)
        
        # Save final ratings
        db.save_ratings(elo.get_driver_ratings())
        print("\nFinal ratings saved to database.")
    else:
        print("No race data was collected.")
    
    db.close()
    return elo.get_driver_ratings()

if __name__ == "__main__":
    # Example: Process data from 2018 to current year
    ratings = process_historical_data(start_year=2018)
    print("\nCurrent Driver Ratings:")
    print(ratings.head(20))