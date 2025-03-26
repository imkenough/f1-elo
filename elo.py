import fastf1
import pandas as pd
import numpy as np
import traceback
import requests
from typing import Optional

fastf1.Cache.enable_cache('f1_cache')

class F1EloRating:
    def __init__(self, initial_rating: float = 1500, k_factor: float = 24):
        self.ratings = {}
        self.initial_rating = initial_rating
        self.k_factor = k_factor
        
    def calculate_expected_score(self, driver_rating: float, opponent_ratings: list) -> float:
        expected_scores = [1 / (1 + 10 ** ((opponent - driver_rating) / 400)) 
                           for opponent in opponent_ratings]
        return sum(expected_scores)
    
    def normalize_race_position(self, position: int, total_drivers: int) -> float:
        position = max(1, min(position, total_drivers))
        return 1 - (position - 1) / (total_drivers - 1)
    
    def update_ratings(self, race_results: pd.DataFrame):
        race_results = race_results.dropna(subset=['Driver', 'Position'])
        
        if len(race_results) < 2:
            print("Not enough valid drivers to calculate ratings")
            return
        
        for driver in race_results['Driver'].unique():
            if driver not in self.ratings:
                self.ratings[driver] = self.initial_rating
        
        total_drivers = len(race_results)
        
        for _, row in race_results.iterrows():
            driver = row['Driver']
            position = int(row['Position'])
            
            opponents = race_results[race_results['Driver'] != driver]
            
            actual_score = self.normalize_race_position(position, total_drivers)
            
            expected_scores = [
                1 / (1 + 10 ** ((self.ratings.get(opponent['Driver'], self.initial_rating) - 
                                 self.ratings[driver]) / 400)) 
                for _, opponent in opponents.iterrows()
            ]
            expected_score = sum(expected_scores) / len(expected_scores)
            
            rating_change = self.k_factor * (actual_score - expected_score)
            self.ratings[driver] += rating_change
    
    def get_driver_ratings(self) -> pd.DataFrame:
        ratings_df = pd.DataFrame.from_dict(self.ratings, orient='index', columns=['Elo Rating'])
        ratings_df = ratings_df[ratings_df['Elo Rating'].notna()]
        return ratings_df.sort_values('Elo Rating', ascending=False)

class F1DataCollector:
    def __init__(self, start_year, end_year):  
        self.start_year = start_year
        self.end_year = end_year
    
    def collect_race_results(self, year: int, race_number: int) -> pd.DataFrame:
        if year >= 2018:
            return self._collect_with_fastf1(year, race_number)
        else:
            return self._collect_with_ergast(year, race_number)
    
    def _collect_with_fastf1(self, year: int, race_number: int) -> pd.DataFrame:
        try:
            schedule = fastf1.get_event_schedule(year)
            
            if race_number > len(schedule):
                print(f"Race {race_number} does not exist in {year}")
                return pd.DataFrame()
            
            session = fastf1.get_session(year, race_number, 'R')
            session.load()
            
            results = session.results
            
            if results is None or len(results) == 0:
                print(f"No results found for {year} Race {race_number}")
                return pd.DataFrame()
            
            driver_column = None
            for col in ['FullName', 'Driver', 'driver']:
                if col in results.columns:
                    driver_column = col
                    break
            
            if driver_column is None:
                print("Could not find driver column")
                return pd.DataFrame()
            
            race_df = pd.DataFrame({
                'Driver': results[driver_column],
                'Position': results['Position']
            })
            
            race_df['Position'] = pd.to_numeric(race_df['Position'], errors='coerce')
            race_df = race_df.dropna()
            
            return race_df
        
        except Exception as e:
            print(f"Error collecting FastF1 results for {year} Race {race_number}: {e}")
            traceback.print_exc()
            return pd.DataFrame()
    
    def _collect_with_ergast(self, year: int, race_number: int) -> pd.DataFrame:
        try:
            url = f"http://ergast.com/api/f1/{year}/{race_number}/results.json"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if not data['MRData']['RaceTable']['Races']:
                print(f"No results found for {year} Race {race_number}")
                return pd.DataFrame()
            
            results = data['MRData']['RaceTable']['Races'][0]['Results']
            drivers = []
            positions = []
            
            for result in results:
                try:
                    given_name = result['Driver']['givenName']
                    family_name = result['Driver']['familyName']
                    driver_name = f"{given_name} {family_name}"
                    position = int(result['position'])
                    
                    drivers.append(driver_name)
                    positions.append(position)
                except (KeyError, ValueError):
                    continue
            
            race_df = pd.DataFrame({
                'Driver': drivers,
                'Position': positions
            })
            
            return race_df
        
        except Exception as e:
            print(f"Error collecting Ergast results for {year} Race {race_number}: {e}")
            traceback.print_exc()
            return pd.DataFrame()

def main():
    elo_system = F1EloRating()
    data_collector = F1DataCollector(start_year=2014, end_year=2025)  
    
    for year in range(data_collector.start_year, data_collector.end_year + 1):
        print(f"\n--- Processing Year {year} ---")
        
        try:
            if year >= 2018:
                schedule = fastf1.get_event_schedule(year)
            else:
                url = f"http://ergast.com/api/f1/{year}.json" #ergastapi idk 
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()
                schedule = data['MRData']['RaceTable']['Races']
            
            total_races = len(schedule)
            print(f"Total races in {year}: {total_races}")
            
            for race_number in range(1, total_races + 1):
                race_result = data_collector.collect_race_results(year, race_number)
                
                if not race_result.empty:
                    print(f"Collected results for {year} Race {race_number}")
                    elo_system.update_ratings(race_result)
        except Exception as e:
            print(f"Error processing year {year}: {e}")
            traceback.print_exc()
            continue
    
    final_ratings = elo_system.get_driver_ratings()
    print("\n--- Final Driver Ratings ---")
    print(final_ratings)
    
    final_ratings.to_csv('elo.csv')

if __name__ == "__main__":
    main()