import random
from utils.timer import timer
from utils.csv_logger import CSVLogger

def benchmark_verification(
    merkle,
    chunks,
    verify_fn,
    num_samples_list,
    repetitions=20
):
    logger = CSVLogger(
        "benchmarking/results/basic_das_week6.csv",
        fieldnames=[
            "phase",
            "num_chunks",
            "samples",
            "avg_verify_ms"
        ]
    )

    root = merkle.root()
    num_chunks = len(chunks)

    for k in num_samples_list:
        times = []
        for _ in range(repetitions):
            indices = random.sample(range(num_chunks), k)
            proofs = [(i, chunks[i], merkle.get_proof(i)) for i in indices]

            with timer() as t:
                for i, chunk, proof in proofs:
                    assert verify_fn(root, chunk, i, proof)
            times.append(t())

        avg_ms = (sum(times) / len(times)) * 1000

        logger.log({
            "phase": "verification",
            "num_chunks": num_chunks,
            "samples": k,
            "avg_verify_ms": avg_ms
        })

    logger.close()