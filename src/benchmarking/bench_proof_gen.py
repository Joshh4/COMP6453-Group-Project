import random
from utils.timer import timer
from utils.csv_logger import CSVLogger

def benchmark_proof_generation(
    merkle,
    chunks,
    num_samples_list,
    repetitions=20
):
    logger = CSVLogger(
        "benchmarking/results/basic_das_week6.csv",
        fieldnames=[
            "phase",
            "num_chunks",
            "samples",
            "avg_proof_gen_ms"
        ]
    )

    num_chunks = len(chunks)

    for k in num_samples_list:
        times = []
        for _ in range(repetitions):
            indices = random.sample(range(num_chunks), k)
            with timer() as t:
                for idx in indices:
                    merkle.get_proof(idx)
            times.append(t())

        avg_ms = (sum(times) / len(times)) * 1000

        logger.log({
            "phase": "proof_generation",
            "num_chunks": num_chunks,
            "samples": k,
            "avg_proof_gen_ms": avg_ms
        })

    logger.close()