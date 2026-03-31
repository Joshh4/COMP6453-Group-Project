import csv
import os

class CSVLogger:
    def __init__(self, filename, fieldnames):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        self.file = open(filename, "w", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=fieldnames)
        self.writer.writeheader()

    def log(self, row: dict):
        self.writer.writerow(row)
        self.file.flush()

    def close(self):
        self.file.close()