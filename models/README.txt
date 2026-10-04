Put your exported model folder(s) here, exactly as they come out of the Colab zip, e.g.

models/
  maize_weed_yolo26n_ncnn_416/        <- unzip maize_weed_yolo26n_ncnn_416.zip here
    robot_config.json
    maize_weed_ncnn_model/
      model.ncnn.param
      model.ncnn.bin
      metadata.yaml
  maize_weed_ncnn_416/                <- (optional) YOLO11n for comparison

The app finds every folder automatically and lets you switch between them in the sidebar.
