import argparse
import glob
import json
import os
import mlflow
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.metrics import roc_curve
import matplotlib.pyplot as plt

def main(args):
    # Load either one CSV file or every CSV file contained in a directory.
    df = get_data(args.training_data)

    # Keep the test set separate so that evaluation uses data unseen during training.
    X_train, X_test, y_train, y_test = split_data(df)

    # Train with the regularization strength supplied on the command line.
    model = train_model(args.reg_rate, X_train, X_test, y_train, y_test)

    # Calculate and log the model's classification metrics.
    metrics = eval_model(model, X_test, y_test)

    # Persist metrics so GitHub Actions can publish the exact values in a PR comment.
    if args.metrics_output:
        save_metrics(metrics, args.metrics_output)

def get_data(path):
    print("Reading data...")

    if os.path.isdir(path):
        # Azure ML commonly mounts folder inputs, so combine all CSV files found there.
        csv_files = glob.glob(os.path.join(path, "*.csv"))
        if not csv_files:
            raise RuntimeError(f"No CSV files found in provided data path: {path}")
        df = pd.concat((pd.read_csv(f) for f in csv_files), ignore_index=True)
    else:
        # Local debugging normally supplies a single CSV file.
        df = pd.read_csv(path)

    return df

def split_data(df):
    print("Splitting data...")
    # Use the clinical measurements as features and Diabetic as the target label.
    X, y = df[['Pregnancies','PlasmaGlucose','DiastolicBloodPressure','TricepsThickness',
    'SerumInsulin','BMI','DiabetesPedigree','Age']].values, df['Diabetic'].values

    # A fixed random state makes the 70/30 split reproducible across runs.
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.30, random_state=0)

    return X_train, X_test, y_train, y_test

# function that trains the model
def train_model(reg_rate, X_train, X_test, y_train, y_test):
    # Record the hyperparameter alongside the run in MLflow.
    mlflow.log_param("Regularization rate", reg_rate)
    print("Training model...")
    # scikit-learn defines C as inverse regularization strength: smaller C means
    # stronger regularization, hence the conversion from reg_rate to 1/reg_rate.
    model = LogisticRegression(C=1/reg_rate, solver="liblinear").fit(X_train, y_train)

    return model

# function that evaluates the model
def eval_model(model, X_test, y_test):
    # Accuracy is the proportion of correctly predicted class labels.
    y_hat = model.predict(X_test)
    acc = np.average(y_hat == y_test)
    print('Accuracy:', acc)
    mlflow.log_metric("Accuracy", acc)

    # ROC AUC measures how well the model ranks diabetic cases above non-diabetic
    # cases across every classification threshold. It complements accuracy, which
    # reflects only one threshold and can hide poor performance on imbalanced data.
    # predict_proba returns one column per class; column 1 is P(Diabetic = 1).
    y_scores = model.predict_proba(X_test)
    auc = roc_auc_score(y_test,y_scores[:,1])
    print('AUC: ' + str(auc))
    mlflow.log_metric("AUC", float(auc))

    # Build the ROC curve from false-positive and true-positive rates.
    fpr, tpr, thresholds = roc_curve(y_test, y_scores[:,1])
    fig = plt.figure(figsize=(6, 4))
    # Plot the diagonal reference representing a random classifier.
    plt.plot([0, 1], [0, 1], 'k--')
    # Plot the trade-off achieved by the trained model at each threshold.
    plt.plot(fpr, tpr)
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('ROC Curve')
    plt.savefig("ROC-Curve.png")
    mlflow.log_artifact("ROC-Curve.png")

    return {
        "accuracy": float(acc),
        "auc": float(auc),
    }

def save_metrics(metrics, output_dir):
    # Create the output folder locally; Azure ML also accepts this as an output path.
    os.makedirs(output_dir, exist_ok=True)
    metrics_path = os.path.join(output_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as metrics_file:
        json.dump(metrics, metrics_file)

    print(f"Saved metrics to {metrics_path}")

def parse_args():
    parser = argparse.ArgumentParser()

    # training_data is overridden with an Azure ML data asset in CI/CD workflows.
    parser.add_argument("--training_data", dest='training_data',
                        type=str)
    # Use the same baseline regularization value for local and remote runs.
    parser.add_argument("--reg_rate", dest='reg_rate',
                        type=float, default=0.1)
    # metrics_output is optional locally and supplied when a workflow needs metrics.json.
    parser.add_argument("--metrics_output", dest='metrics_output',
                        type=str, default=None)

    # parse args
    args = parser.parse_args()

    # return args
    return args

# run script
if __name__ == "__main__":
    # Delimit this script's output in local terminals and Azure ML logs.
    print("\n\n")
    print("*" * 60)

    args = parse_args()

    main(args)

    # add space in logs
    print("*" * 60)
    print("\n\n")
