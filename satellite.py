import argparse
import itertools
import json
import math

import matplotlib.pyplot as plt
import dimod
import numpy as np
from qdeepsdk import QDeepHybridSolver


def read_in_args():
    """Read in user specified parameters."""
    parser = argparse.ArgumentParser(description='Satellites example')
    parser.add_argument('file', metavar='file', type=str, help='Input file')
    parser.add_argument('solver', metavar='solver', type=str, help='Solver')
    return parser.parse_args()


# For independent events, Pr(at least one event)=1−Pr(none of the events)
# https://math.stackexchange.com/questions/85849/calculating-the-probability-that-at-least-one-of-a-series-of-events-will-happen
def calculate_score(constellation, data):
    """Calculate the constellation score."""
    score = 1
    for v in constellation:
        score *= (1 - data['coverage'][str(v)])
    score = 1 - score
    return score


def build_bqm(data, constellation_size):
    """Build the BQM for the problem."""
    # Do not consider constellations with an average score less than score_threshold
    score_threshold = 0.4

    bqm = dimod.BinaryQuadraticModel.empty(dimod.BINARY)

    # First, favor combinations with a high score
    for constellation in itertools.combinations(range(data['num_satellites']), constellation_size):
        # The score is the probability that at least one satellite in the constellation
        # has line of sight over the target at any one time.
        score = calculate_score(constellation, data)

        # Discard combinations with a score below the set threshold
        if score < score_threshold:
            continue

        # Subtract the score because we want to minimize the energy
        bqm.add_variable(frozenset(constellation), -score)

    # Next, penalize pairs that share a satellite (penalty strength 2)
    for c0, c1 in itertools.combinations(bqm.variables, 2):
        if c0.isdisjoint(c1):
            continue
        bqm.add_interaction(c0, c1, 2)

    # Finally, enforce choosing exactly num_constellations variables.
    # Use a strength of 1 so that it is not advantageous to violate the constraint by picking extra variables.
    bqm.update(dimod.generators.combinations(bqm.variables, data['num_constellations'], strength=1))

    return bqm


def viz(constellations, data):
    """Visualize the solution."""
    angle = 2 * math.pi / data["num_satellites"]

    # Display scatter plot data
    plt.figure()
    plt.title('Constellations')

    s = 0
    for c in constellations:
        x = []
        y = []
        label = []
        for satellite in c:
            coverage = 1 - data["coverage"][str(satellite)]
            label.append(satellite)
            x.append(coverage * math.cos(s * angle))
            y.append(coverage * math.sin(s * angle))
            s += 1

        x.append(x[0])
        y.append(y[0])
        label.append(label[0])
        plt.plot(x, y, marker='o', markersize=1)

    plt.scatter([0], [0], marker='*', color='#7f7f7f', s=500)
    plt.axis('off')

    # Save plot
    plt.savefig('constellations.png')


if __name__ == '__main__':
    args = read_in_args()

    with open(args.file, 'r') as fp:
        data = json.load(fp)

    # Each of the satellites (labeled 0 to num_satellites-1) has a coverage score.
    constellation_size = data['num_satellites'] // data['num_constellations']

    bqm = build_bqm(data, constellation_size)

    # Replace the SimulatedAnnealingSampler with QDeepHybridSolver.
    # Convert the BQM to a QUBO dictionary and an offset.
    qubo, offset = bqm.to_qubo()

    # Create a mapping from variable (frozenset) to index.
    variables = list(bqm.variables)
    mapping = {var: i for i, var in enumerate(variables)}
    n = len(variables)
    matrix = np.zeros((n, n))
    for (var_i, var_j), coeff in qubo.items():
        i = mapping[var_i]
        j = mapping[var_j]
        matrix[i, j] = coeff

    # Initialize QDeepHybridSolver and set the authentication token.
    solver = QDeepHybridSolver()
    solver.token = "your-auth-token-here"  # Replace with your valid token

    # Use the solver based on the chosen argument.
    # For 'neal' we emulate multiple reads; for 'hss' we do a single read.
    if args.solver == 'hss':
        num_reads = 1
        samples = []
        energies = []
        for _ in range(num_reads):
            result = solver.solve(matrix)
            sample = result.get('sample')
            # Map sample indices back to variables
            sample_dict = {variables[i]: sample.get(i, 0) for i in range(n)}
            energy = bqm.energy(sample_dict)
            samples.append(sample_dict)
            energies.append(energy)
        best_index = np.argmin(energies)
        best_sample = samples[best_index]
    else:
        print("satellite.py: Unrecognized solver")
        exit(1)

    # Extract constellations from the best sample (variables with value 1)
    constellations = [constellation for constellation, chosen in best_sample.items() if chosen]

    tot = 0
    for constellation in constellations:
        score = calculate_score(constellation, data)
        print("Constellation: " + str(constellation) + ", Score: " + str(score))
        tot += score
    print("Total Score: " + str(tot))
    print("Normalized Score (tot / # constellations): " + str((tot / data['num_constellations'])))

    viz(constellations, data)
