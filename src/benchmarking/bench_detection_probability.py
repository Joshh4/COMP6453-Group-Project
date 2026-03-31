import random
from utils.csv_logger import CSVLogger

def benchmark_detection_probability(
    merkle,
    chunks,
    verify_fn,
    withholding_ratio_list,
    samples,
    trials=200
):
    logger = CSVLogger(
        "benchmarking/results/basic_das_week6.csv",
        fieldnames=[
            "phase",
            "num_chunks",
            "withholding_ratio",
            "samples",
            "detection_probability"
        ]
    )

    root = merkle.root()
    num_chunks = len(chunks)

    for w in withholding_ratio_list:
        failures = 0
        withheld = set(random.sample(
            range(num_chunks),
            int(w * num_chunks)
        ))

        for _ in range(trials):
            indices = random.sample(range(num_chunks), samples)
            detected = False

            for idx in indices:
                if idx in withheld:
                    detected = True
                    break

            if not detected:
                failures += 1

        detection_probability = 1 - failures / trials

        logger.log({
            "phase": "detection_probability",
            "num_chunks": num_chunks,
            "withholding_ratio": w,
            "samples": samples,
            "detection_probability": detection_probability
        })

    logger.close()
